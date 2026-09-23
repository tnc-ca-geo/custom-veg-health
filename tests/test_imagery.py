from datetime import date

from custom_veg_health import imagery


def test_composite_year_round_trips_asset_id():
    asset_id = imagery.composite_asset_id(2019)
    assert asset_id.endswith('/Landsat_SR_medoid_2019_2019_152_273')
    assert imagery.composite_year(asset_id) == 2019


def test_composite_year_ignores_other_assets():
    assert imagery.composite_year('x/Landsat_SR_medoid_2019_2020_152_273') is None
    assert imagery.composite_year('x/Landsat_SR_medoid_2019_2019_190_250') is None
    assert imagery.composite_year('x/readme') is None


def test_available_years_follows_pages(monkeypatch):
    pages = {
        None: {'assets': [
                   {'id': imagery.composite_asset_id(1986)},
                   {'id': 'projects/p/assets/c/not_a_composite'}],
               'nextPageToken': 'next'},
        'next': {'assets': [{'name': imagery.composite_asset_id(1985)}]},
    }
    monkeypatch.setattr(
        imagery.ee.data, 'listAssets',
        lambda params: pages[params.get('pageToken')])
    assert imagery.available_years() == [1985, 1986]


def test_water_year_status():
    assert imagery.water_year_status(2026, date(2026, 9, 30)) == 'incomplete'
    assert imagery.water_year_status(2026, date(2026, 10, 1)) == 'provisional'
    assert imagery.water_year_status(2025, date(2026, 9, 14)) == 'final'
