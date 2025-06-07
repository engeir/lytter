"""The home page of the app."""

import reflex as rx

from ..config import UPDATE_PASSWORD

# from .. import styles
from ..templates import template
from ..tools.download_scrobbles import GetScrobbles


class HiddenState(rx.State):
    hidden: str = ""
    predefined: str = str(UPDATE_PASSWORD)


# def password_page():
#     return rx.vstack(
#         rx.input(
#             placeholder="Enter password",
#             type="password",
#             value=PasswordState.password,
#             on_change=PasswordState.set_password,
#         ),
#         rx.button(
#             "Submit",
#             on_click=...,
#             disabled=PasswordState.password != PasswordState.predefined,
#         ),
#     )


class UpdateData(rx.State):
    text = "Update database"
    placeholder = "Enter database secret"

    def full_update(self):
        GetScrobbles().full_update()


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
            rx.input(
                placeholder=UpdateData.placeholder,
                type="password",
                value=HiddenState.hidden,
                on_change=HiddenState.set_hidden,
            ),
            rx.button(
                UpdateData.text,
                on_click=UpdateData.full_update,
                disabled=HiddenState.hidden != HiddenState.predefined,
            ),
            # rx.button(UpdateData.text, on_click=UpdateData.update),
            # rx.button(
            #     "Refresh ...",
            #     on_click=GetScrobbles().save(),
            #     # width="10%",
            # ),
        ),
    )
