from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def example_gpkg():
    return str(ROOT / 'examples' / 'example.gpkg')


@pytest.fixture
def published_csv():
    return ROOT / 'tests' / 'data' / 'published_example.csv'
