"""
Parity with published GDE Pulse values. Calls Earth Engine:

    EE_PROJECT=my-ee-project pytest -m ee

tests/data/published_example.csv holds the web app's values for the ten
example polygons, taken from https://gde.codefornature.org/data/gde_v24_1.csv.
The bulk download rounds NDVI and NDMI to 4 decimals and precipitation to whole
inches. Measured in September 2026, the median NDVI/NDMI difference was at that
rounding level, but a few values differed by up to 0.00075, worst on the
smallest polygon. Edge interpretation, polygon geometry (identical to NC dataset
v2.0) and the composites (pixel-identical) were all ruled out; the residual is
most likely Earth Engine's edge-pixel weighting when the published values were
computed. Indices are therefore compared to within 0.001.
"""
import os

import pandas as pd
import pytest

import custom_veg_health as cvh

pytestmark = pytest.mark.ee


@pytest.fixture(scope='module')
def comparison(request):
    project = os.environ.get('EE_PROJECT')
    if not project:
        pytest.skip('set EE_PROJECT to run Earth Engine tests')
    cvh.initialize(project)
    root = request.config.rootpath
    published = pd.read_csv(root / 'tests' / 'data' / 'published_example.csv')
    polygons = cvh.read_polygons(
        str(root / 'examples' / 'example.gpkg'), 'polygon_id')
    years = sorted(set(published.year) & set(cvh.available_years()))
    ours = cvh.extract(polygons, years)
    return published.rename(columns={'gde': 'polygon_id'}).merge(
        ours, on=['polygon_id', 'year'], suffixes=('_pub', ''))


def test_all_published_years_available(comparison):
    missing = sorted(set(range(1985, 2026)) - set(comparison.year))
    assert not missing, (
        f'no composite for {cvh.describe_years(missing)} in '
        f'{cvh.imagery.COMPOSITE_COLLECTION}')


@pytest.mark.parametrize('index', ['ndvi', 'ndmi'])
def test_indices_match(comparison, index):
    diff = (comparison[index].round(4) - comparison[f'{index}_pub']).abs()
    assert diff.max() <= 1e-3, comparison.loc[diff.idxmax()]


def test_precipitation_matches(comparison):
    diff = (comparison.precip_in.round() - comparison.precip).abs()
    assert diff.max() <= 1, comparison.loc[diff.idxmax()]
