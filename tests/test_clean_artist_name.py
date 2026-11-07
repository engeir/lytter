"""Unit test for clean_artist_name()."""

import pytest

from lytter.app import clean_artist_name


def test_clean_artist_strips_listening_unit() -> None:
    """Trailing `(on <unit>)` scrobbler artefact is removed."""
    assert clean_artist_name("Beach House (on Bad)") == "Beach House"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Beach House (ON BAD)", "Beach House"),
        ("Slowdive (on TV i stuen) ", "Slowdive"),
        ("Drongo [on Bad]", "Drongo"),
        ("  X   (on Bad)", "X"),
    ],
)
def test_clean_artist_strips_variants(raw, expected):
    """Strip is case-insensitive, tolerates spacing and bracket style."""
    assert clean_artist_name(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "(on Radio)",  # stripping would leave an empty name
        "Chicago (with Cello)",  # only 'on' counts
        "X (on Y) Z",  # mid-string group is not trailing
        "Terror (on)",  # no unit name after 'on'
        "Beach House",  # already clean
    ],
)
def test_clean_artist_preserves_real_names(raw):
    """Names that are not a trailing listening-unit artifact are untouched."""
    assert clean_artist_name(raw) == raw
