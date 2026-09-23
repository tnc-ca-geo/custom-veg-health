import pytest

from custom_veg_health import (
    SetupError, describe_years, parse_years, resolve_years)


@pytest.mark.parametrize('text, expected', [
    (None, None),
    ('', None),
    ('2020', [2020]),
    ('2018-2020', [2018, 2019, 2020]),
    ('2020, 1990-1991,2020', [1990, 1991, 2020]),
])
def test_parse_years(text, expected):
    assert parse_years(text) == expected


@pytest.mark.parametrize('text', ['twenty', '2020-2010', '2010-'])
def test_parse_years_rejects(text):
    with pytest.raises(SetupError):
        parse_years(text)


def test_describe_years():
    assert describe_years([1985, 1986, 1987, 1990, 2000, 2001]) \
        == '1985-1987, 1990, 2000-2001'


def test_resolve_years_defaults_to_all():
    assert resolve_years(None, [1985, 1986]) == [1985, 1986]


def test_resolve_years_names_missing_and_available():
    with pytest.raises(SetupError, match='No composite for 2026.*1985-2025'):
        resolve_years([2024, 2026], list(range(1985, 2026)))
