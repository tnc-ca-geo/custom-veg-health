import geopandas as gpd
import pytest
from shapely.geometry import Point, Polygon

from custom_veg_health import SetupError, read_polygons
from custom_veg_health.zonal import chunk_features, to_features

SQUARE = Polygon([(0, 0), (0, 0.001), (0.001, 0.001), (0.001, 0)])
BOWTIE = Polygon([(0, 0), (0.001, 0.001), (0.001, 0), (0, 0.001)])


def write(tmp_path, ids, geoms, crs='EPSG:4326'):
    path = tmp_path / 'polys.gpkg'
    gpd.GeoDataFrame({'ID': ids}, geometry=geoms, crs=crs).to_file(path)
    return str(path)


def test_reads_example_and_reprojects(example_gpkg):
    polygons = read_polygons(example_gpkg, 'polygon_id')
    assert len(polygons) == 10
    assert list(polygons.columns) == ['polygon_id', 'geometry']
    assert polygons.crs.to_epsg() == 4326
    minx, miny, maxx, maxy = polygons.total_bounds
    assert -125 < minx < maxx < -114 and 32 < miny < maxy < 42


def test_missing_field_lists_fields(example_gpkg):
    with pytest.raises(SetupError, match='vegetation'):
        read_polygons(example_gpkg, 'POLYGON_ID')


def test_duplicate_ids(tmp_path):
    with pytest.raises(SetupError, match='unique'):
        read_polygons(write(tmp_path, [1, 1], [SQUARE, SQUARE]), 'ID')


def test_missing_ids(tmp_path):
    with pytest.raises(SetupError, match='no .ID. value'):
        read_polygons(write(tmp_path, [1, None], [SQUARE, SQUARE]), 'ID')


def test_missing_crs(tmp_path):
    path = tmp_path / 'nocrs.shp'
    gpd.GeoDataFrame(
        {'ID': [1]}, geometry=[SQUARE], crs='EPSG:4326').to_file(path)
    path.with_suffix('.prj').unlink()
    with pytest.raises(SetupError, match='coordinate reference system'):
        read_polygons(str(path), 'ID')


def test_points_rejected(tmp_path):
    with pytest.raises(SetupError, match='Only polygons'):
        read_polygons(write(tmp_path, [1], [Point(0, 0)]), 'ID')


def test_invalid_polygon_repaired(tmp_path):
    polygons = read_polygons(write(tmp_path, [1, 2], [BOWTIE, SQUARE]), 'ID')
    assert polygons.is_valid.all()
    assert polygons.geom_type.isin(['Polygon', 'MultiPolygon']).all()


def test_features_carry_only_id(example_gpkg):
    features = to_features(read_polygons(example_gpkg, 'polygon_id'))
    assert features[0]['properties'] == {'polygon_id': 25762}
    assert features[0]['geometry']['type'] == 'Polygon'


def test_chunking_by_count_and_size():
    feature = {'type': 'Feature', 'properties': {'polygon_id': 1},
               'geometry': SQUARE.__geo_interface__}
    assert [len(c) for c in chunk_features([feature] * 5, max_features=2)] \
        == [2, 2, 1]
    size = len(__import__('json').dumps(feature))
    assert [len(c) for c in chunk_features([feature] * 3, max_bytes=size)] \
        == [1, 1, 1]
