import sys

import pendulum
import pylast

from ..config import API_KEY, API_SECRET, PASSWORD_HASH, TIME_ZONE, USER_NAME

# You have to have your own unique two values for API_KEY and API_SECRET
# Obtain yours from https://www.last.fm/api/account for Last.fm

lastfm_network = pylast.LastFMNetwork(
    api_key=API_KEY,
    api_secret=API_SECRET,
    username=USER_NAME,
    password_hash=PASSWORD_HASH,
)


def track_and_timestamp(track):
    my_time = TIME_ZONE.convert(
        pendulum.from_format(track.playback_date, "DD MMM YYYY, HH:mm")
    )
    out_time = my_time.format("DD MMM YYYY, HH:mm")
    return f"{out_time}\t{track.track}"


TRACK_SEPARATOR = " - "


def split_artist_track(artist_track):
    artist_track = artist_track.replace(" – ", " - ")
    artist_track = artist_track.replace("“", '"')
    artist_track = artist_track.replace("”", '"')

    (artist, track) = artist_track.split(TRACK_SEPARATOR)
    artist = artist.strip()
    track = track.strip()
    print("Artist:\t\t'" + artist + "'")
    print("Track:\t\t'" + track + "'")

    # Validate
    if len(artist) == 0 and len(track) == 0:
        sys.exit("Error: Artist and track are blank")
    if len(artist) == 0:
        sys.exit("Error: Artist is blank")
    if len(track) == 0:
        sys.exit("Error: Track is blank")

    return (artist, track)


# End of file
