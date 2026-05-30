"""Unit tests for normalize_name()."""

import pytest

from lytter.app import normalize_name


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Case
        ("Angine de Poitrine", "angine de poitrine"),
        ("RADIOHEAD", "radiohead"),
        # Whitespace
        ("  Sigur  Rós  ", "sigur ros"),
        # Diacritics
        ("Sigur Rós", "sigur ros"),
        ("Björk", "bjork"),
        ("café tacvba", "cafe tacvba"),
        # Ampersand (with spaces)
        ("Simon & Garfunkel", "simon and garfunkel"),
        # Ampersand without spaces — not matched
        ("Simon&Garfunkel", "simon&garfunkel"),
    ],
)
def test_normalize_artist(raw, expected):
    """Normalize artist name: lowercase, diacritics stripped, ampersand expanded."""
    assert normalize_name(raw, "artist") == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Song (feat. Other Artist)", "song feat. other artist"),
        ("Song (Feat. Other Artist)", "song feat. other artist"),
        ("Song [feat. Other]", "song feat. other"),
        ("Song ft. Other", "song feat. other"),
        ("Song featuring Other", "song feat. other"),
        ("Song feat Other", "song feat. other"),  # bare feat without period
    ],
)
def test_normalize_track_feat(raw, expected):
    """Normalize track feat. variants to canonical 'feat.' form."""
    assert normalize_name(raw, "track") == expected


def test_normalize_artist_feat_unchanged():
    """Feat. variants are NOT restructured for artist field — only lowercased."""
    result = normalize_name("Artist feat. Other", "artist")
    assert result == "artist feat. other"


def test_normalize_empty():
    """Empty string returns empty string for any field."""
    assert normalize_name("", "artist") == ""
    assert normalize_name("", "track") == ""


def test_normalize_album():
    """Normalize album name: lowercase and diacritics stripped."""
    assert normalize_name("OK Computer", "album") == "ok computer"
    assert normalize_name("Ágætis byrjun", "album") == "agætis byrjun"  # æ is a ligature, not NFD-decomposable
