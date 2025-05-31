"""Download and update Lastfm scrobbles."""

import reflex as rx
import requests
import sqlalchemy
import sqlmodel

from ..config import API_KEY, USER_NAME


class MusicLibrary(rx.Model, table=True):
    """The full lastfm scrobbles library."""

    artist: str
    artist_mbid: str
    album: str
    album_mbid: str
    track: str
    track_mbid: str
    timestamp: int = sqlmodel.Field(unique=True)


class GetScrobbles:
    """Download and update your scrobbles CSV."""

    def __init__(self):
        self.pause_duration = 0.2
        self.existing_items = self._get_items()
        self.method = "recenttracks"

    def _get_items(self) -> set:
        try:
            items = set(self.ds["timestamp"].tolist())
        except KeyError:
            items = set()
        return items

    def get_scrobbles(
        self, limit: int = 200, extended: int = 0, page: int = 1, pages: int = 0
    ) -> None:
        """Get scrobbles via the lastfm API.

        Parameters
        ----------
        limit : int
            The API lets you retrieve up to 200 records per call
        extended : int
            Th API lets you retrieve extended data for each track, 0=no, 1=yes
        page : int
            The page of results to start retrieving at
        pages : int
            The number of pages of results to retrieve. if 0, get as many as api can
            return.
        """
        # initialize url and lists to contain response fields
        url = "https://ws.audioscrobbler.com/2.0/?method=user.get{}&user={}&api_key={}&limit={}&extended={}&page={}&format=json"

        # make first request, just to get the total number of pages
        request_url = url.format(self.method, USER_NAME, API_KEY, limit, extended, page)
        response = requests.get(request_url).json()
        total_pages = int(response[self.method]["@attr"]["totalPages"])
        if pages > 0:
            total_pages = min([total_pages, pages])
        print(f"{total_pages} total pages to retrieve")

        # request each page of data one at a time
        found_existing = False
        for page_ in range(1, int(total_pages) + 1):
            # if not page_ % 22:
            #     break
            print(f"Page {page_}/{total_pages}", end="\r")
            # time.sleep(self.pause_duration)
            request_url = url.format(
                self.method, USER_NAME, API_KEY, limit, extended, page_
            )
            response = requests.get(request_url)
            scrobbles = response.json()
            for scrobble in scrobbles[self.method]["track"]:
                # Only retain completed scrobbles (aka, with timestamp and not 'now
                # playing'). Also check if it has been downloaded already.
                if "@attr" in scrobble and scrobble["@attr"]["nowplaying"] == "true":
                    continue
                the_scrobble = {
                    "artist": scrobble["artist"]["#text"],
                    "artist_mbid": scrobble["artist"]["mbid"],
                    "album": scrobble["album"]["#text"],
                    "album_mbid": scrobble["album"]["mbid"],
                    "track": scrobble["name"],
                    "track_mbid": scrobble["mbid"],
                    "timestamp": scrobble["date"]["uts"],
                }
                new_song = MusicLibrary(**the_scrobble)
                with rx.session() as session:
                    session.add(new_song)
                    try:
                        session.commit()
                    except sqlalchemy.exc.IntegrityError:
                        session.rollback()
                        found_existing = True
            if found_existing:
                break

        print("Scrobbles are up to date!")


def main() -> None:
    """Run the downloader."""
    down = GetScrobbles()
    print(down.existing_items)
    down.get_scrobbles()


if __name__ == "__main__":
    main()
