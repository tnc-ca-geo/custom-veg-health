"""
Earth Engine images used by custom-veg-health. Nothing here contacts Earth Engine until an image is evaluated, so importing this module needs no credentials.
"""
from __future__ import annotations

import re
from datetime import date

import ee

# Annual dry-season (June 1 - September 30) Landsat surface reflectance medoid
# composites, produced for TNC by Ian Housman (RedCastle Resources). Public;
# a new year is added about once a year.
COMPOSITE_COLLECTION = 'projects/gde-ca/assets/composite-collection'

# Daily PRISM, 4 km. Supersedes OREGONSTATE/PRISM/AN81d, which ends 2020-12-30.
PRISM_COLLECTION = 'OREGONSTATE/PRISM/ANd'

# PRISM daily values are re-modelled until six months have passed.
PRISM_PROVISIONAL_DAYS = 183

# e.g. Landsat_SR_medoid_2019_2019_152_273 = day-of-year 152-273 of 2019
_COMPOSITE_NAME = re.compile(r'Landsat_SR_medoid_(\d{4})_\1_152_273$')


def composite_year(asset_id: str) -> int | None:
    """
    Year of a composite asset, or None if the name isn't a composite.
    """
    match = _COMPOSITE_NAME.search(asset_id.rsplit('/', 1)[-1])
    return int(match.group(1)) if match else None


def composite_asset_id(year: int, collection: str = COMPOSITE_COLLECTION) -> str:
    """
    Asset id of the composite for a year.
    """
    return f'{collection}/Landsat_SR_medoid_{year}_{year}_152_273'


def available_years(collection: str = COMPOSITE_COLLECTION) -> list[int]:
    """
    Years that have a composite in the collection. Requires ee.Initialize().
    """
    years = set()
    params = {'parent': collection}
    while True:
        response = ee.data.listAssets(params)
        for asset in response.get('assets', []):
            year = composite_year(asset.get('id') or asset.get('name', ''))
            if year:
                years.add(year)
        token = response.get('nextPageToken')
        if not token:
            return sorted(years)
        params = {'parent': collection, 'pageToken': token}


def ndvi(image: ee.Image) -> ee.Image:
    """
    Add an NDVI band: (NIR - red) / (NIR + red).
    """
    return image.addBands(
        image.normalizedDifference(['nir', 'red']).rename('ndvi'))


def ndmi(image: ee.Image) -> ee.Image:
    """
    Add an NDMI band: (NIR - SWIR1) / (NIR + SWIR1).
    """
    return image.addBands(
        image.normalizedDifference(['nir', 'swir1']).rename('ndmi'))


def medoid_image(year: int, collection: str = COMPOSITE_COLLECTION) -> ee.Image:
    """
    NDVI and NDMI bands from the dry-season medoid composite of a year.
    """
    image = ee.Image(composite_asset_id(year, collection)).select(
        ['red', 'nir', 'swir1'])
    return ndmi(ndvi(image)).select(['ndvi', 'ndmi'])


def precipitation_image(year: int) -> ee.Image:
    """
    Total precipitation, in inches, for the water year ending in `year`.

    The date filter is copied exactly from the production pipeline.
    """
    return (
        ee.ImageCollection(PRISM_COLLECTION)
        .filterDate(f'{year - 1}-10-01', f'{year}-09-30')
        .select('ppt')
        .sum()
        .divide(25.4)
        .rename('precip_in'))


def water_year_status(year: int, today: date | None = None) -> str:
    """
    'incomplete' before the water year ends, 'provisional' while PRISM may
    still revise it, otherwise 'final'.
    """
    today = today or date.today()
    end = date(year, 9, 30)
    if today <= end:
        return 'incomplete'
    if (today - end).days < PRISM_PROVISIONAL_DAYS:
        return 'provisional'
    return 'final'
