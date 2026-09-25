from __future__ import annotations

import json
import logging
import time
from datetime import date
from typing import Callable, Sequence

import ee
import geopandas as gpd
import pandas as pd
import shapely

from . import imagery

logger = logging.getLogger(__name__)

SETUP_DOCS = (
    'https://github.com/tnc-ca-geo/custom-veg-health#earth-engine-access')

VEG_SCALE = 30
PRECIP_SCALE = 120
CRS = 'EPSG:4326'
TILE_SCALE = 2

# Earth Engine rejects request payloads over about 10 MB.
MAX_FEATURES_PER_REQUEST = 200
MAX_BYTES_PER_REQUEST = 2_000_000

ID = 'polygon_id'
COLUMNS = [ID, 'year', 'ndvi', 'ndmi', 'precip_in']

# Error text that means "ask for less at once" versus "ask again later".
_SPLIT_ON = ('memory limit', 'payload', 'request size', 'timed out')
_RETRY_ON = (
    'too many concurrent', 'internal error', 'deadline', 'unavailable',
    'backend error', 'try again')


class SetupError(RuntimeError):
    """
    A problem the user can fix; the message says how.
    """


def initialize(project: str | None, authenticate: bool = False) -> None:
    """
    Start Earth Engine and confirm the composites are readable.

    Args:
        project: Google Cloud project registered for Earth Engine.
        authenticate: sign in first (opens a browser).
    """
    try:
        if authenticate:
            ee.Authenticate()
        ee.Initialize(project=project)
        # A cheap real request, so a misconfigured project fails now rather
        # than partway through a run.
        ee.data.listAssets(
            {'parent': imagery.COMPOSITE_COLLECTION, 'pageSize': 1})
    except Exception as err:  # auth errors come from google-auth too
        raise SetupError(_explain(err, project)) from err


def _explain(err: Exception, project: str | None) -> str:
    text = str(err)
    lowered = text.lower()
    if 'authenticate' in lowered or 'credentials' in lowered:
        hint = (
            'No Earth Engine credentials were found. Pass --authenticate to '
            'sign in (it opens a browser), or run the tool with no arguments '
            'and it will offer to. Sign in with your own Google account. '
            'No TNC account is needed.')
    elif not project:
        hint = (
            'Earth Engine needs a Google Cloud project. Pass '
            '--project YOUR-PROJECT-ID or set EE_PROJECT.')
    elif 'not registered' in lowered or 'has not been used' in lowered \
            or 'disabled' in lowered:
        hint = f'Project {project!r} is not registered for Earth Engine.'
    elif 'permission' in lowered or 'not found' in lowered:
        hint = (
            f'Your account could not use project {project!r} or read '
            f'{imagery.COMPOSITE_COLLECTION}. Check that your account belongs '
            'to the project and that its Earth Engine access is active.')
    else:
        hint = 'Earth Engine could not start.'
    return f'{hint}\nSetup guide: {SETUP_DOCS}\nEarth Engine said: {text}'


def read_polygons(
    path: str, id_field: str, layer: str | None = None
) -> gpd.GeoDataFrame:
    """
    Read and check polygons.

    Accepts anything GDAL reads: shapefile (or a zip of one), GeoPackage,
    GeoJSON, file geodatabase, KML.

    Returns:
        GeoDataFrame with columns polygon_id and geometry, in EPSG:4326.
    """
    gdf = gpd.read_file(path, layer=layer)
    fields = [col for col in gdf.columns if col != gdf.geometry.name]
    if id_field not in fields:
        raise SetupError(
            f'No field {id_field!r} in {path}. Fields: {", ".join(fields)}')
    if gdf.crs is None:
        raise SetupError(
            f'{path} has no coordinate reference system (for a shapefile, '
            'the .prj file is missing).')
    ids = gdf[id_field]
    if ids.isna().any():
        raise SetupError(
            f'{int(ids.isna().sum())} polygons have no {id_field!r} value.')
    repeated = ids[ids.duplicated()].unique()
    if len(repeated):
        raise SetupError(
            f'{id_field!r} must be unique. Repeated: '
            f'{", ".join(map(str, repeated[:5]))}')

    gdf = gpd.GeoDataFrame(
        {ID: ids.to_numpy()}, geometry=gdf.geometry.to_numpy(),
        crs=gdf.crs).to_crs(CRS)
    gdf = _check_geometry(gdf)
    logger.info('Read %d polygons from %s', len(gdf), path)
    return gdf


def _check_geometry(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    empty = gdf.geometry.isna() | gdf.geometry.is_empty
    if empty.any():
        raise SetupError(
            'Polygons with no geometry: '
            f'{", ".join(map(str, gdf.loc[empty, ID][:5]))}')
    other = set(gdf.geom_type) - {'Polygon', 'MultiPolygon'}
    if other:
        raise SetupError(
            f'Only polygons are supported; found {", ".join(sorted(other))}.')
    invalid = ~gdf.is_valid
    if invalid.any():
        logger.warning('Repairing %d invalid polygons', int(invalid.sum()))
        gdf.loc[invalid, 'geometry'] = gdf.loc[invalid, 'geometry'].apply(
            _repair)
        if gdf.geometry.is_empty.any():
            raise SetupError(
                'These polygons could not be repaired: '
                f'{", ".join(map(str, gdf.loc[gdf.geometry.is_empty, ID]))}')
    return gdf


def _repair(geom):
    """
    make_valid can return lines or points alongside polygons; keep polygons.
    """
    fixed = shapely.make_valid(geom)
    if fixed.geom_type in ('Polygon', 'MultiPolygon'):
        return fixed
    return shapely.union_all([
        part for part in getattr(fixed, 'geoms', [])
        if part.geom_type in ('Polygon', 'MultiPolygon')])


def parse_years(text: str | None) -> list[int] | None:
    """
    '2010-2025', '2018,2020' or '1990-1999,2015' to a sorted list; None for
    all available years.
    """
    if not text:
        return None
    years = set()
    try:
        for part in text.replace(' ', '').split(','):
            if '-' in part:
                start, end = (int(value) for value in part.split('-', 1))
                if start > end:
                    raise ValueError
                years.update(range(start, end + 1))
            elif part:
                years.add(int(part))
    except ValueError:
        raise SetupError(
            f'Could not read years {text!r}. Use e.g. 2010-2025 or 2018,2020.'
        ) from None
    return sorted(years)


def describe_years(years: Sequence[int]) -> str:
    """
    [1985, 1986, 1987, 1990] -> '1985-1987, 1990'
    """
    spans, start = [], None
    for index, year in enumerate(years):
        start = year if start is None else start
        if index + 1 == len(years) or years[index + 1] != year + 1:
            spans.append(str(year) if start == year else f'{start}-{year}')
            start = None
    return ', '.join(spans)


def resolve_years(
    requested: Sequence[int] | None, available: Sequence[int]
) -> list[int]:
    """
    Check requested years against the composites that exist.
    """
    if not available:
        raise SetupError('No composites were found in the collection.')
    if requested is None:
        return list(available)
    missing = sorted(set(requested) - set(available))
    if missing:
        raise SetupError(
            f'No composite for {describe_years(missing)}. Available: '
            f'{describe_years(available)}. New years are added about once '
            'a year, after the dry season ends.')
    return list(requested)


def to_features(polygons: gpd.GeoDataFrame) -> list[dict]:
    """
    GeoJSON features carrying only polygon_id.
    """
    return json.loads(polygons[[ID, 'geometry']].to_json(drop_id=True))[
        'features']


def chunk_features(
    features: Sequence[dict],
    max_features: int = MAX_FEATURES_PER_REQUEST,
    max_bytes: int = MAX_BYTES_PER_REQUEST,
) -> list[list[dict]]:
    """
    Group features into requests small enough for Earth Engine.
    """
    chunks, current, size = [], [], 0
    for feature in features:
        nbytes = len(json.dumps(feature))
        if current and (
                len(current) >= max_features or size + nbytes > max_bytes):
            chunks.append(current)
            current, size = [], 0
        current.append(feature)
        size += nbytes
    if current:
        chunks.append(current)
    return chunks


def _reduce_chunk(image: ee.Image, chunk: list[dict], scale: int) -> list[dict]:
    """
    Mean of every band of `image` over each feature, as property dicts.
    """
    collection = ee.FeatureCollection(
        {'type': 'FeatureCollection', 'features': chunk})
    reduced = image.reduceRegions(
        collection=collection,
        reducer=ee.Reducer.mean().forEachBand(image),
        scale=scale, crs=CRS, tileScale=TILE_SCALE,
    ).select(['.*'], None, False)
    return [item['properties'] for item in reduced.getInfo()['features']]


def _reduce(
    image: ee.Image, chunk: list[dict], scale: int, attempts: int = 4,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict]:
    """
    _reduce_chunk, splitting requests that are too big and retrying
    transient failures. (The ee library already retries rate limits.)
    """
    for attempt in range(attempts):
        try:
            return _reduce_chunk(image, chunk, scale)
        except ee.EEException as err:
            message = str(err).lower()
            if len(chunk) > 1 and any(s in message for s in _SPLIT_ON):
                half = len(chunk) // 2
                return (
                    _reduce(image, chunk[:half], scale, attempts, sleep)
                    + _reduce(image, chunk[half:], scale, attempts, sleep))
            if attempt + 1 < attempts and any(s in message for s in _RETRY_ON):
                wait = 5 * 2 ** attempt
                logger.warning('%s - retrying in %d s', err, wait)
                sleep(wait)
                continue
            raise
    raise AssertionError('unreachable')


def extract(
    polygons: gpd.GeoDataFrame,
    years: Sequence[int],
    include_precip: bool = True,
    collection: str = imagery.COMPOSITE_COLLECTION,
    today: date | None = None,
) -> pd.DataFrame:
    """
    NDVI, NDMI and water-year precipitation for each polygon and year.

    Returns:
        One row per polygon per year. A blank value means no pixel counted:
        the polygon is far smaller than a 30 m pixel, or every pixel was
        masked (cloud, missing data) in that year's composite.
    """
    features = to_features(polygons)
    chunks = chunk_features(features)
    columns = COLUMNS if include_precip else COLUMNS[:-1]
    rows = []
    for index, year in enumerate(years, 1):
        logger.info('%d (%d of %d)', year, index, len(years))
        values = {
            feature['properties'][ID]: {ID: feature['properties'][ID],
                                        'year': year}
            for feature in features}
        _collect(values, imagery.medoid_image(year, collection), chunks,
                 VEG_SCALE)
        if include_precip:
            status = imagery.water_year_status(year, today)
            if status == 'incomplete':
                logger.warning(
                    'Water year %d has not ended; precip_in left blank', year)
            else:
                if status == 'provisional':
                    logger.warning(
                        'Precipitation for water year %d is provisional; PRISM '
                        'may still revise it', year)
                _collect(values, imagery.precipitation_image(year), chunks,
                         PRECIP_SCALE)
        rows.extend(values.values())
    return pd.DataFrame(rows, columns=columns)


def _collect(
    values: dict, image: ee.Image, chunks: list[list[dict]], scale: int
) -> None:
    for chunk in chunks:
        for properties in _reduce(image, chunk, scale):
            row = values[properties.pop(ID)]
            row.update(properties)
