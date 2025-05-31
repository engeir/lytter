"""Get lyrics from Genius."""

from lyricsgenius import Genius

from ..config import GENIUS_TOKEN


def _setup() -> Genius:
    return Genius(GENIUS_TOKEN)


def get_lyrics(artist: str, song: str) -> str:
    """Search up the lyrics of a song by an artist."""
    g = _setup()
    g.verbose = False
    s = g.search_song(song, artist=artist)
    match s:
        case None:
            return "No lyrics found :("
        case _:
            return s.lyrics


if __name__ == "__main__":
    l = get_lyrics("Low", "Hey")
    print("#" * 80)
    print(l)
