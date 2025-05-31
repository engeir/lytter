"""Set global configuration values."""

import os

import pendulum
import pylast
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET")
USER_NAME = os.environ.get("USER_NAME")
PASSWORD = os.environ.get("PASSWORD")
PASSWORD_HASH = pylast.md5(PASSWORD)
GENIUS_TOKEN = os.environ.get("GENIUS_TOKEN")
# API_KEY = subprocess.check_output(["pass", "Lastfm/API_KEY"]).strip().decode()
# API_SECRET = subprocess.check_output(["pass", "Lastfm/API_SECRET"]).strip().decode()
# USER_NAME = subprocess.check_output(["pass", "Lastfm/Username"]).strip().decode()
# PASSWORD = subprocess.check_output(["pass", "Lastfm/Password"]).strip().decode()
# PASSWORD_HASH = pylast.md5(PASSWORD)
# GENIUS_TOKEN = subprocess.check_output(["pass", "Genius/Client-access-token"]).strip().decode()

TIME_ZONE = pendulum.timezone("Europe/Oslo")

if __name__ == "__main__":
    print(API_KEY)
    print(API_SECRET)
    print(USER_NAME)
    print(PASSWORD)
    print(PASSWORD_HASH)
    print(GENIUS_TOKEN)
