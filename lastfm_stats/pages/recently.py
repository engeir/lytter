"""The dashboard page."""

import pylast
import reflex as rx

from ..config import USER_NAME
from ..templates import template
from ..tools.mylast import lastfm_network


class Recently:
    def __init__(self) -> None:
        self.now_playing = "Nothing is playing"

    def reset(self) -> None:
        self.now_playing = ""

    def find_now_playing(self) -> pylast.Track:
        self.reset()
        try:
            now_playing = lastfm_network.get_user(USER_NAME).get_recent_tracks()
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


class RecentState(rx.State):
    recent_tracks = ""


@template(route="/recently", title="Recently")
def recently() -> rx.Component:
    """The recently played page.

    Returns
    -------
        The UI for the recently played page.
    """
    return rx.vstack(
        rx.heading("Recently played", font_size="3em"),
        rx.text(
            "You can edit this page in ",
            rx.code("{your_app}/pages/dashboard.py"),
        ),
    )
