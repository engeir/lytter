"""The home page of the app."""

import reflex as rx

# from .. import styles
from ..templates import template
from ..tools.download_scrobbles import GetScrobbles


class UpdateData(rx.State):
    text = "Update!"

    def update(self):
        GetScrobbles().save()


@template(route="/", title="Home", image="/github.svg")
def index() -> rx.Component:
    """Landing page of the website.

    Returns
    -------
        The UI for the home page.
    """
    # with open("README.md", encoding="utf-8") as readme:
    #     content = readme.read()
    # return rx.markdown(content, component_map=styles.markdown_style)
    return rx.center(
        rx.vstack(
            rx.heading("My Music Stats", font_size="3em"),
            rx.markdown(
                r"""
                There is more to come here, but for now, go check out the
                [Now Playing](/now-playing) page.
                """,
            ),
            rx.button(UpdateData.text, on_click=UpdateData.update),
            # rx.button(
            #     "Refresh ...",
            #     on_click=GetScrobbles().save(),
            #     # width="10%",
            # ),
        )
    )
