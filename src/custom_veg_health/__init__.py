"""
NDVI, NDMI and water-year precipitation for custom polygons, using the GDE
Pulse dry-season Landsat composites in Google Earth Engine.

    import custom_veg_health as cvh

    cvh.initialize('my-ee-project')
    polygons = cvh.read_polygons('gdes.gpkg', id_field='POLYGON_ID')
    years = cvh.resolve_years(cvh.parse_years('2010-2025'), cvh.available_years())
    table = cvh.extract(polygons, years)
"""
__version__ = '0.1.0'

from .zonal import (  # noqa: E402
    SetupError, describe_years, extract, initialize, parse_years,
    read_polygons, resolve_years)
from .imagery import available_years  # noqa: E402

__all__ = [
    'SetupError', 'available_years', 'describe_years', 'extract',
    'initialize', 'parse_years', 'read_polygons', 'resolve_years']
