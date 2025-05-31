"""The now-playing page."""

import plotly.express as px
import pylast
import reflex as rx
import reflex_chakra as rc

from ..config import USER_NAME
from ..templates import template
from ..tools.get_lyrics import get_lyrics
from ..tools.mylast import lastfm_network
from ..tools.stats_lookup import CurrentStats


def _convert_ms_to_hms(milliseconds: float | str) -> str:
    ms = float(milliseconds)
    seconds = int((ms / 1000) % 60)
    minutes = int(ms / (1000 * 60))
    time_format = f"{minutes} min {seconds} sec"
    return time_format


class NowPlaying:
    def __init__(self) -> None:
        self.now_playing = "Nothing is playing"

    def reset(self) -> None:
        self.now_playing = ""

    def not_a_song(self) -> None:
        self.now_playing = "Nothing is playing"

    def find_now_playing(self) -> pylast.Track:
        self.reset()
        try:
            now_playing = lastfm_network.get_user(USER_NAME).get_now_playing()
            if now_playing is not None:
                return now_playing
        except (
            pylast.MalformedResponseError,
            pylast.NetworkError,
            pylast.WSError,
        ) as e:
            print(f"Error: {e}", "error")
        else:
            return "I'm not listening to music atm :/"


def list_to_written_listing(elements: list[str]) -> str:
    """Convert a list of elements to a written list ending with 'and'."""
    all_but_one = '", "'.join(elements[:-1])
    return f'{all_but_one}", and "{elements[-1]}'


class NowPlayingState(rx.State):
    """The app state."""

    now_playing = ""
    song = ""
    album_cover = ""
    playcount = ""
    artist = ""
    artist_playcount = ""
    artist_top_albums = ""
    artist_top_tracs = ""
    artist_similar = ""
    album = ""
    album_playcount = ""
    duration = ""
    info = ""
    lyrics = ""
    figure_history = px.line()
    figure_top_songs = px.line()
    processing = False
    complete = False
    playing = False

    def get_nowplaying(self) -> None:
        """Get the currently playing audio."""
        self.processing, self.complete = True, False
        yield
        response = NowPlaying().find_now_playing()
        self.now_playing = str(response)
        match response:
            case "I'm not listening to music atm :/":
                self.playing = False
            case _:
                self._update_now_playing_attributes(response)
        self.processing, self.complete = False, True
        yield

    @staticmethod
    def _protected_response(response: pylast.Track, method: str) -> str:
        try:
            out = getattr(response, method)()
        except pylast.WSError:
            out = "Not found"
        return out

    def _update_now_playing_attributes(self, response: pylast.Track) -> None:
        self.playing = True
        self.song = self._protected_response(response, "get_name")
        self.album_cover = self._protected_response(response, "get_cover_image")
        self.playcount = self._protected_response(response, "get_userplaycount")
        artist = response.get_artist()
        artist.username = USER_NAME
        self.artist = artist.get_name()
        self.artist_playcount = self._protected_response(artist, "get_userplaycount")
        if self.song == "Not found" or self.playcount == "Not found":
            NowPlaying().not_a_song()
            self.playing = False
            return
        # self.artist_top_tracs = str(artist.get_top_tracks(limit=5)[0])
        # self.artist_top_albums = str(artist.get_top_albums(limit=5))
        self.artist_top_tracs = (
            '"'
            + list_to_written_listing(
                [a.item.get_name() for a in artist.get_top_tracks(limit=5)]
            )
            + '"'
        )
        self.artist_top_albums = (
            '"'
            + list_to_written_listing(
                [a.item.get_name() for a in artist.get_top_albums(limit=5)]
            )
            + '"'
        )
        self.artist_similar = (
            '"'
            + list_to_written_listing(
                [a.item.get_name() for a in artist.get_similar(limit=5)]
            )
            + '"'
        )
        self.album = response.get_album().get_name()
        self.album_playcount = response.get_album().get_userplaycount()
        self.duration = _convert_ms_to_hms(response.get_duration())
        self.info = response.get_mbid()
        self.lyrics = get_lyrics(self.artist, self.song)
        current_stats = CurrentStats()
        self.figure_history = current_stats.listening_history_db(self.artist)
        self.figure_top_songs = current_stats.top_songs(self.artist)


# class NowPlayingStats(rx.State):
#     """Statistics about the song and artist that is playing."""
#
#     figure = CurrentStats().listening_history_db(str(NowPlayingState.artist))
#
#     # def set_selected_country(self, country):
#     #     self.df = px.data.gapminder().query(f"country=='{country}'")
#     #     self.figure = px.line(
#     #         self.df,
#     #         x="year",
#     #         y="lifeExp",
#     #         title=f"Life expectancy in {country}",
#     #     )


# def line_chart_with_state() -> rx.vstack:
#     return rx.vstack(
#         # rx.select(
#         #     [
#         #         "China",
#         #         "France",
#         #         "United Kingdom",
#         #         "United States",
#         #         "Canada",
#         #     ],
#         #     # default_value="Canada",
#         #     # on_change=NowPlayingState.set_selected_country,
#         # ),
#         rx.plotly(data=NowPlayingStats.figure),
#     )


@template(route="/now-playing", title="Now Playing")
def now_playing() -> rx.Component:
    """Run the component for the now-playing page.

    Returns
    -------
    rx.Component
        The UI for the now-playing page.
    """
    list_item_color = "purple"
    return rx.vstack(
        rx.heading("Now Playing", font_size="3em"),
        rx.button(
            "What are you listening to, Eirik?",
            on_click=NowPlayingState.get_nowplaying,
            loading=NowPlayingState.processing,
            width="100%",
        ),
        rx.cond(
            NowPlayingState.complete,
            rc.heading(NowPlayingState.now_playing, color="purple", size="md"),
        ),
        rx.cond(
            NowPlayingState.playing,
            rx.vstack(
                rc.hstack(
                    rx.image(src=NowPlayingState.album_cover),
                    # https://reflex.dev/docs/library/chakra/media/icon/
                    rc.list(
                        rc.list_item(
                            rc.icon(tag="time", color=list_item_color),
                            f" It is {NowPlayingState.duration} long",
                        ),
                        rc.list_item(
                            rc.icon(tag="repeat", color=list_item_color),
                            f" I have listened to this track {NowPlayingState.playcount} times :)",
                        ),
                        rc.list_item(
                            rc.icon(tag="repeat", color=list_item_color),
                            f" I have listened to the album {NowPlayingState.album} {NowPlayingState.album_playcount} times :)",
                        ),
                        rc.list_item(
                            rc.icon(tag="repeat", color=list_item_color),
                            f" I have listened to {NowPlayingState.artist} {NowPlayingState.artist_playcount} times :)",
                        ),
                        rc.list_item(
                            rc.icon(tag="star", color=list_item_color),
                            f" Their top 5 songs are {NowPlayingState.artist_top_tracs}",
                        ),
                        rc.list_item(
                            rc.icon(tag="sun", color=list_item_color),
                            f" Their top 5 albums are {NowPlayingState.artist_top_albums}",
                        ),
                        rc.list_item(
                            rc.icon(tag="view", color=list_item_color),
                            f" If you enjoy listening to {NowPlayingState.artist}, here are five similar artists! {NowPlayingState.artist_similar}",
                        ),
                        rc.list_item(
                            rc.icon(tag="lock", color=list_item_color),
                            f" It's MusicBrainz ID is {NowPlayingState.info}",
                        ),
                        width="100%",
                    ),
                    spacing="10%",
                    width="80%",
                ),
                rx.vstack(
                    rx.markdown("## Lyrics"),
                    rx.markdown(
                        "I searched on [Genius](https://genius.com/) for the lyrics of "
                        + f'"{NowPlayingState.artist}" (artist) and "{NowPlayingState.song}" (song), '
                        + "and this is what I found:"
                    ),
                    rx.box(
                        rx.code_block(
                            NowPlayingState.lyrics,
                            language="markup",
                            copy_button=True,
                            wrap_long_lines=True,
                            show_line_numbers=True,
                        ),
                        height="50vh",
                        width="80%",
                        overflow_y="auto",
                    ),
                ),
                rx.center(
                    rx.plotly(data=NowPlayingState.figure_history),
                ),
                rx.center(
                    rx.plotly(data=NowPlayingState.figure_top_songs),
                ),
            ),
        ),
    )
