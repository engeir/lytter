"""Search the database for stats about an artist and a song."""

import datetime
from collections import Counter, OrderedDict

import plotly.express as px
import reflex as rx

if __name__ == "__main__":
    from lastfm.tools.download_scrobbles import MusicLibrary
else:
    from .download_scrobbles import MusicLibrary


class CurrentStats:
    """Show stats about a given artist."""

    def listening_history_db(self, artist: str) -> px.line:
        """Drop the artist listening history into a cumulative line plot."""
        with rx.session() as session:
            out: list[MusicLibrary] = session.exec(
                MusicLibrary.select().where(MusicLibrary.artist == artist)
            ).all()
        dates = [datetime.datetime.fromtimestamp(o.timestamp) for o in out]
        dates.sort()
        counts = list(range(1, len(out) + 1))
        fig = px.line(x=dates, y=counts, title="Listening history")
        fig.update_layout(
            title_x=0.5,
            xaxis_title="Time",
            yaxis_title="Count",
            showlegend=True,
            title_font_family="Open Sans",
            title_font_size=25,
        )
        return fig

    def top_songs(self, artist: str) -> px.line:
        """Drop the top songs of an artist into a bar plot."""
        with rx.session() as session:
            out: list[MusicLibrary] = session.exec(
                MusicLibrary.select().where(MusicLibrary.artist == artist)
            ).all()
        songs = OrderedDict(Counter(o.track for o in out).most_common())
        unique_songs = list(songs.keys())[::-1]
        song_counts = list(songs.values())[::-1]
        length = max(len(unique_songs) * 30, 100)
        fig = px.bar(
            x=song_counts,
            y=unique_songs,
            orientation="h",
            title="Top songs",
            height=length,
        )
        fig.update_layout(
            title_x=0.5,
            xaxis_title="Count",
            yaxis_title="Track",
            showlegend=True,
            title_font_family="Open Sans",
            title_font_size=25,
        )
        return fig


if __name__ == "__main__":
    s = CurrentStats()
    s.top_songs("Coil")
