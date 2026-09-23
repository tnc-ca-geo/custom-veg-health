"""
Guided prompts, with questionary and Earth Engine replaced by fakes.
"""
import json

import pandas as pd
import pytest

from custom_veg_health import interactive as ui
from custom_veg_health.cli import main as cli_main


def test_field_choices_disables_fields_that_cannot_be_ids():
    table = pd.DataFrame({
        'name': ['a', 'a', 'b'],
        'POLY_ID': [7, 8, 9],
        'code': ['x', 'y', 'z'],
        'notes': ['n', None, 'm'],
        'empty': [None, None, None],
    })
    choices, default = ui.field_choices(table)
    status = {c.value: c.disabled for c in choices}
    assert status == {'POLY_ID': None, 'code': None, 'name': 'repeated values',
                      'notes': '1 blank', 'empty': 'empty'}
    assert default.value == 'POLY_ID'
    assert [c.value for c in choices][:2] == ['POLY_ID', 'code']


def test_field_choices_needs_a_usable_field():
    with pytest.raises(ui.SetupError, match='unique value'):
        ui.field_choices(pd.DataFrame({'name': ['a', 'a']}))


def test_validate_polygon_file(example_gpkg, tmp_path):
    assert ui.validate_polygon_file(f' "{example_gpkg}" ') is True
    assert 'Nothing found' in ui.validate_polygon_file(str(tmp_path / 'no.gpkg'))
    junk = tmp_path / 'junk.gpkg'
    junk.write_text('not a geopackage')
    assert 'Could not read' in ui.validate_polygon_file(str(junk))


def test_validate_years():
    available = list(range(1985, 2026))
    assert ui.validate_years('2010-2025', available) is True
    assert 'No composite for 2026' in ui.validate_years('2026', available)
    assert 'Could not read' in ui.validate_years('soon', available)


def test_saved_project(monkeypatch, tmp_path):
    credentials = tmp_path / 'credentials'
    monkeypatch.setattr(ui.ee.oauth, 'get_credentials_path',
                        lambda: str(credentials))
    assert ui.saved_project() is None
    credentials.write_text(json.dumps({'project': 'my-proj'}))
    assert ui.saved_project() == 'my-proj'


def test_estimate_minutes():
    assert ui.estimate_minutes(300, 41, precip=True) == 27
    assert ui.estimate_minutes(10, 1, precip=False) == 1


class Script:
    """
    Answers prompts in order, checking each against the prompt's validator.
    """

    def __init__(self, *steps):
        self.steps = list(steps)
        self.asked = []

    def __call__(self, kind, message, **kwargs):
        expected, answer = self.steps.pop(0)
        assert expected in message, f'expected {expected!r}, got {message!r}'
        self.asked.append(message)
        if answer is ui.Cancelled:
            raise ui.Cancelled
        if 'validate' in kwargs:
            assert kwargs['validate'](answer) is True
        return answer


@pytest.fixture
def fake_ee(monkeypatch, tmp_path):
    credentials = tmp_path / 'credentials'
    credentials.write_text(json.dumps({'project': 'saved-proj'}))
    monkeypatch.setattr(ui.ee.oauth, 'get_credentials_path',
                        lambda: str(credentials))
    monkeypatch.delenv('EE_PROJECT', raising=False)
    monkeypatch.delenv('GOOGLE_CLOUD_PROJECT', raising=False)
    calls = {}
    monkeypatch.setattr(ui, 'initialize', lambda project, authenticate: calls.update(
        project=project, authenticate=authenticate))
    monkeypatch.setattr(ui.imagery, 'available_years',
                        lambda: list(range(1985, 2026)))

    def extract(polygons, years, include_precip):
        calls.update(years=years, precip=include_precip)
        return pd.DataFrame({'polygon_id': polygons.polygon_id, 'year': years[0]})

    monkeypatch.setattr(ui, 'extract', extract)
    return calls


def test_guided_run(monkeypatch, fake_ee, example_gpkg, tmp_path, capsys):
    output = tmp_path / 'out.csv'
    script = Script(
        ('Polygon file', example_gpkg),
        ('Which field', 'polygon_id'),
        ('project ID', 'saved-proj'),
        ('Which years', 'some'),
        ('Years', '2020-2022'),
        ('precipitation', False),
        ('Save results', str(output)),
        ('Start', True),
    )
    monkeypatch.setattr(ui, '_ask', script)
    assert ui.main() == 0
    assert fake_ee == {'project': 'saved-proj', 'authenticate': False,
                       'years': [2020, 2021, 2022], 'precip': False}
    assert len(pd.read_csv(output)) == 10
    command = capsys.readouterr().out
    assert '--years 2020-2022 --no-precip --output' in command


def test_cancel_writes_nothing(monkeypatch, fake_ee, example_gpkg, capsys):
    monkeypatch.setattr(ui, '_ask', Script(
        ('Polygon file', example_gpkg), ('Which field', ui.Cancelled)))
    assert ui.main() == 130
    assert 'nothing written' in capsys.readouterr().err
    assert 'years' not in fake_ee


def test_no_arguments_outside_a_terminal(monkeypatch, capsys):
    monkeypatch.setattr('sys.stdin.isatty', lambda: False)
    assert cli_main([]) == 2
    assert 'guided prompts' in capsys.readouterr().err
