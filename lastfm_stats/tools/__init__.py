"""Module holding the scripts found in lastfm-tools.

https://github.com/hugovk/lastfm-tools
"""

import pathlib

here = pathlib.Path(__file__)
while not ((root := here.parent) / ".git").is_dir():
    here = root

DATA_PATH = root / "data"
DATA_PATH.mkdir(parents=True, exist_ok=True)
