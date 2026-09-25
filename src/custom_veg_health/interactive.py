"""
TUI, for running `custom-veg-health` with no arguments.
"""
from __future__ import annotations

import json
import logging
import math
import os
import shlex
import sys
from pathlib import Path
from typing import Any

import ee
import pandas as pd
import pyogrio
import questionary
from questionary import Choice

from . import imagery
from .cli import program_name
from .zonal import (
    MAX_FEATURES_PER_REQUEST, SETUP_DOCS, SetupError, describe_years, extract,
    initialize, parse_years, read_polygons, resolve_years)

logger = logging.getLogger('custom_veg_health')

# The tool is designed for a few hundred polygons; confirm before much more.
LARGE_JOB = 1000

# Measured wall-clock seconds per request per year; see README.
SECONDS_PER_REQUEST = {True: 20, False: 5}


class Cancelled(Exception):
    """
    The user stopped at a prompt.
    """


def _ask(kind: str, message: str, **kwargs) -> Any:
    """
    Show one questionary prompt. Tests replace this function.
    """
    answer = getattr(questionary, kind)(message, **kwargs).ask(kbi_msg='')
    if answer is None:  # Ctrl+C
        raise Cancelled
    return answer


def clean_path(text: str) -> Path:
    return Path(text.strip().strip('\'"')).expanduser()


def polygon_layers(path: Path) -> list[str]:
    return [
        str(name) for name, kind in pyogrio.list_layers(path)
        if kind and ('Polygon' in kind or kind == 'Unknown')]


def validate_polygon_file(text: str) -> bool | str:
    if not text.strip():
        return 'Enter the path to your polygon file.'
    path = clean_path(text)
    if not path.exists():
        return f'Nothing found at {path}'
    try:
        if not polygon_layers(path):
            return 'That file has no polygon layers.'
    except Exception:  # pyogrio raises several error types
        return 'Could not read that file. Try a .gpkg, .shp, zipped .shp or .geojson.'
    return True


def field_choices(table: pd.DataFrame) -> tuple[list[Choice], Choice]:

    usable, unusable = [], []
    for field in table.columns:
        values = table[field]
        blank = values.isna() | (values.astype(str).str.strip() == '')
        if blank.all():
            unusable.append(Choice(field, field, disabled='empty'))
        elif blank.any():
            unusable.append(Choice(field, field, disabled=f'{int(blank.sum())} blank'))
        elif values.duplicated().any():
            unusable.append(Choice(field, field, disabled='repeated values'))
        else:
            usable.append(Choice(f'{field}  (e.g. {values.iloc[0]})', field))
    if not usable:
        raise SetupError(
            'No field has a unique value for every polygon. Add an ID field '
            'to the file and try again.')
    default = next(
        (choice for choice in usable if 'id' in choice.value.lower()), usable[0])
    return usable + unusable, default


def validate_years(text: str, available: list[int]) -> bool | str:
    try:
        requested = parse_years(text)
        if requested is None:
            return 'Enter years, e.g. 2010-2025 or 2015,2020,2025.'
        resolve_years(requested, available)
    except SetupError as err:
        return str(err)
    return True


def saved_project() -> str | None:
    """
    Project saved with `earthengine set_project`, if any.
    """
    try:
        with open(ee.oauth.get_credentials_path(), encoding='utf-8') as handle:
            return json.load(handle).get('project')
    except (OSError, ValueError):
        return None


def default_output(path: Path) -> Path:
    return path.with_name(f'{path.stem}_veg_health.csv')


def estimate_minutes(polygons: int, years: int, precip: bool) -> int:
    requests = math.ceil(polygons / MAX_FEATURES_PER_REQUEST)
    return max(1, round(years * requests * SECONDS_PER_REQUEST[precip] / 60))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    try:
        return _run()
    except Cancelled:
        print('Cancelled; nothing written.', file=sys.stderr)
        return 130
    except SetupError as err:
        print(f'error: {err}', file=sys.stderr)
        return 2


def _run() -> int:
    print(
        'custom-veg-health: NDVI, NDMI and precipitation for your polygons.\n'
        'Press Ctrl+C at any prompt to stop.\n')

    path = clean_path(_ask(
        'path', 'Polygon file:', validate=validate_polygon_file))
    layers = polygon_layers(path)
    layer = layers[0] if len(layers) == 1 else _ask(
        'select', 'Which layer?', choices=layers)

    count = pyogrio.read_info(path, layer=layer)['features']
    if count > LARGE_JOB and not _ask(
            'confirm',
            f'{count:,} polygons is more than this tool is designed for (a few '
            'hundred), so it will be slow. Continue?', default=False):
        raise Cancelled
    table = pyogrio.read_dataframe(path, layer=layer, read_geometry=False)
    choices, default = field_choices(table)
    id_field = _ask(
        'select', 'Which field identifies each polygon?', choices=choices,
        default=default)
    polygons = read_polygons(str(path), id_field, layer)

    project = _connect()

    available = imagery.available_years()
    which = _ask('select', 'Which years?', choices=[
        Choice(f'All available ({describe_years(available)})', 'all'),
        Choice('Choose a range or list', 'some')])
    years = available if which == 'all' else parse_years(_ask(
        'text', 'Years (e.g. 2010-2025 or 2015,2020,2025):',
        validate=lambda text: validate_years(text, available)))

    precip = _ask(
        'confirm', 'Include water-year precipitation? It takes about three '
        'quarters of the run time.', default=True)

    output = _ask_output(default_output(path))

    command = [*program_name().split(), '--polygons', str(path),
               '--id-field', id_field, '--project', project]
    if len(layers) > 1:
        command += ['--layer', layer]
    if years != available:
        command += ['--years', describe_years(years).replace(' ', '')]
    if not precip:
        command.append('--no-precip')
    if output != default_output(path):
        command += ['--output', str(output)]
    minutes = estimate_minutes(len(polygons), len(years), precip)
    print(
        f'\n{len(polygons)} polygons x {len(years)} years, roughly '
        f'{minutes} min.\nTo repeat this run without prompts:\n'
        f'  {shlex.join(command)}\n')
    if not _ask('confirm', 'Start?', default=True):
        raise Cancelled

    table = extract(polygons, years, include_precip=precip)
    table.to_csv(output, index=False)
    logger.info('Wrote %d rows to %s', len(table), output)
    return 0


def _connect() -> str:
    """
    Sign in if needed and start Earth Engine. Returns the project ID.
    """
    authenticate = False
    if not os.path.exists(ee.oauth.get_credentials_path()):
        if not _ask(
                'confirm', 'You are not signed in to Earth Engine on this '
                'computer. Sign in now? (opens a browser)', default=True):
            raise SetupError(
                'Sign in with `python -c "import ee; ee.Authenticate()"`, '
                'then run again.\n'
                f'Setup guide: {SETUP_DOCS}')
        authenticate = True
    project = (os.environ.get('EE_PROJECT')
               or os.environ.get('GOOGLE_CLOUD_PROJECT') or saved_project()
               or '')
    while True:
        project = _ask(
            'text', 'Earth Engine project ID:', default=project,
            validate=lambda text: bool(text.strip())
            or f'Enter your Cloud project ID. Setup guide: {SETUP_DOCS}'
        ).strip()
        try:
            initialize(project, authenticate=authenticate)
            return project
        except SetupError as err:
            print(f'\n{err}\n', file=sys.stderr)
            authenticate = False
            if not _ask('confirm', 'Try a different project?', default=True):
                raise Cancelled from None


def _ask_output(suggested: Path) -> Path:
    while True:
        output = clean_path(_ask('path', 'Save results as:', default=str(suggested)))
        if not output.exists() or _ask(
                'confirm', f'{output} exists. Replace it?', default=False):
            return output
