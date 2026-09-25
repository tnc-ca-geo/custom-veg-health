"""
extract() with Earth Engine replaced by fakes: images are tagged strings and
reductions return canned properties.
"""
from datetime import date

import ee
import pytest

from custom_veg_health import zonal as ex
from custom_veg_health.cli import main


@pytest.fixture
def fake_ee(monkeypatch):
    calls = []
    monkeypatch.setattr(ex.imagery, 'medoid_image',
                        lambda year, collection: ('veg', year))
    monkeypatch.setattr(ex.imagery, 'precipitation_image',
                        lambda year: ('precip', year))

    def reduce_chunk(image, chunk, scale):
        kind, year = image
        calls.append((kind, year, scale, len(chunk)))
        out = []
        for feature in chunk:
            pid = feature['properties']['polygon_id']
            if kind == 'veg':
                # polygon 25770 has no pixels in 2001
                props = {} if (pid, year) == (25770, 2001) else {
                    'ndvi': 0.5, 'ndmi': 0.2}
            else:
                props = {'precip_in': 20.0}
            out.append({'polygon_id': pid, **props})
        return out

    monkeypatch.setattr(ex, '_reduce_chunk', reduce_chunk)
    return calls


def test_one_row_per_polygon_year(fake_ee, example_gpkg):
    polygons = ex.read_polygons(example_gpkg, 'polygon_id')
    table = ex.extract(polygons, [2000, 2001], today=date(2026, 9, 14))
    assert list(table.columns) == ex.COLUMNS
    assert len(table) == 20
    blank = table[(table.polygon_id == 25770) & (table.year == 2001)]
    assert blank[['ndvi', 'ndmi']].isna().all(axis=None)
    assert table.precip_in.eq(20.0).all()
    assert {(kind, scale) for kind, _, scale, _ in fake_ee} \
        == {('veg', 30), ('precip', 120)}


def test_unfinished_water_year_has_blank_precip(fake_ee, example_gpkg):
    polygons = ex.read_polygons(example_gpkg, 'polygon_id')
    table = ex.extract(polygons, [2026], today=date(2026, 9, 14))
    assert table.precip_in.isna().all()
    assert table.ndvi.notna().all()


def test_no_precip(fake_ee, example_gpkg):
    polygons = ex.read_polygons(example_gpkg, 'polygon_id')
    table = ex.extract(polygons, [2000], include_precip=False)
    assert 'precip_in' not in table.columns
    assert all(kind == 'veg' for kind, *_ in fake_ee)


def test_reduce_splits_oversized_requests(monkeypatch):
    sizes = []

    def reduce_chunk(image, chunk, scale):
        sizes.append(len(chunk))
        if len(chunk) > 1:
            raise ee.EEException('User memory limit exceeded.')
        return [chunk[0]]

    monkeypatch.setattr(ex, '_reduce_chunk', reduce_chunk)
    assert ex._reduce(None, [1, 2, 3], 30) == [1, 2, 3]
    assert sizes == [3, 1, 2, 1, 1]


def test_reduce_retries_transient_errors(monkeypatch):
    attempts, waits = [], []

    def reduce_chunk(image, chunk, scale):
        attempts.append(1)
        if len(attempts) < 3:
            raise ee.EEException('Too many concurrent aggregations.')
        return ['ok']

    monkeypatch.setattr(ex, '_reduce_chunk', reduce_chunk)
    assert ex._reduce(None, [1], 30, sleep=waits.append) == ['ok']
    assert waits == [5, 10]


def test_reduce_raises_other_errors(monkeypatch):
    def reduce_chunk(image, chunk, scale):
        raise ee.EEException('Image.load: Asset not found.')

    monkeypatch.setattr(ex, '_reduce_chunk', reduce_chunk)
    with pytest.raises(ee.EEException, match='not found'):
        ex._reduce(None, [1, 2], 30, sleep=lambda s: None)


def test_cli_reports_bad_field_without_touching_ee(example_gpkg, capsys):
    assert main(['--polygons', example_gpkg, '--id-field', 'nope']) == 2
    assert 'No field' in capsys.readouterr().err


def test_explain_missing_credentials():
    message = ex._explain(
        ee.EEException('Please authorize access to your Earth Engine '
                       'account by running earthengine authenticate'), 'p')
    assert 'No TNC account is needed' in message
    assert ex.SETUP_DOCS in message


@pytest.mark.parametrize('argv0, expected', [
    ('/env/lib/site-packages/custom_veg_health/__main__.py',
     'python -m custom_veg_health'),
    ('/env/bin/custom-veg-health', 'custom-veg-health'),
])
def test_help_names_the_command_the_user_typed(monkeypatch, capsys, argv0, expected):
    from custom_veg_health.cli import build_parser
    monkeypatch.setattr('sys.argv', [argv0])
    build_parser().print_help()
    assert f'  {expected} --polygons gdes.gpkg' in capsys.readouterr().out
