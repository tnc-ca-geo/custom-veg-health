"""
Command line interface: custom-veg-health --polygons x.gpkg --id-field ID ...
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from . import __version__, imagery
from .zonal import (
    SetupError, describe_years, extract, initialize, parse_years,
    read_polygons, resolve_years)

logger = logging.getLogger('custom_veg_health')

EXAMPLES = """
Run with no arguments for guided prompts.

examples:
  custom-veg-health --polygons gdes.gpkg --id-field POLYGON_ID --project my-ee-project
  custom-veg-health --polygons gdes.zip --id-field ID --years 2010-2025 -o out.csv
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='custom-veg-health',
        description=(
            'NDVI, NDMI and water-year precipitation for each of your '
            'polygons, from the GDE Pulse dry-season Landsat composites.'),
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        '--polygons', required=True,
        help='polygon file: .gpkg, .shp, zipped shapefile, .geojson, ...')
    parser.add_argument(
        '--id-field', required=True,
        help='field with a unique id for each polygon')
    parser.add_argument(
        '--project',
        default=os.environ.get('EE_PROJECT')
        or os.environ.get('GOOGLE_CLOUD_PROJECT'),
        help='Google Cloud project registered for Earth Engine '
             '(default: $EE_PROJECT)')
    parser.add_argument(
        '--years',
        help='e.g. 2010-2025 or 2018,2020 (default: every available year)')
    parser.add_argument(
        '--layer', help='layer name, for files with several layers')
    parser.add_argument(
        '-o', '--output',
        help='CSV to write (default: <polygons>_veg_health.csv)')
    parser.add_argument(
        '--no-precip', action='store_true', help='skip precipitation')
    parser.add_argument(
        '--authenticate', action='store_true',
        help='sign in to Earth Engine before running')
    parser.add_argument(
        '--collection', default=imagery.COMPOSITE_COLLECTION,
        help=argparse.SUPPRESS)
    parser.add_argument(
        '-q', '--quiet', action='store_true', help='only print problems')
    parser.add_argument(
        '--version', action='version', version=f'%(prog)s {__version__}')
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv in (['-i'], ['--interactive']):
        if not sys.stdin.isatty():
            print('error: no arguments. Pass --polygons and --id-field, or run '
                  'in a terminal for guided prompts. See --help.',
                  file=sys.stderr)
            return 2
        from .interactive import main as interactive_main
        return interactive_main()
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format='%(message)s')
    polygons_path = Path(args.polygons)
    output = Path(args.output) if args.output else polygons_path.with_name(
        f'{polygons_path.stem}_veg_health.csv')
    try:
        requested = parse_years(args.years)
        polygons = read_polygons(str(polygons_path), args.id_field, args.layer)
        initialize(args.project, authenticate=args.authenticate)
        years = resolve_years(
            requested, imagery.available_years(args.collection))
        logger.info('Years: %s', describe_years(years))
        table = extract(
            polygons, years, include_precip=not args.no_precip,
            collection=args.collection)
    except SetupError as err:
        print(f'error: {err}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('interrupted; nothing written', file=sys.stderr)
        return 130
    table.to_csv(output, index=False)
    logger.info('Wrote %d rows to %s', len(table), output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
