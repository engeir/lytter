"""Welcome to Reflex."""

import reflex as rx

# Import all the pages.
from .pages import index, now_playing  # noqa: F401

# Create the app and compile it.
app = rx.App(
    theme=rx.theme(
        appearance="inherit",
        has_background=True,
        radius="large",
        accent_color="purple",
    )
    # style=styles.base_style
)
# app.compile()
