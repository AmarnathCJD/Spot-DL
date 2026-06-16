"""Spot-DL entry point.

Imports the aiohttp Application from `web` and runs it. All business logic
lives in the imported modules:

    spotify_audio.py  AES-CTR decrypt + Ogg header rebuild
    spotify.py        Session, search, metadata, radio, playlist
    web.py            aiohttp routes + ffmpeg video composition

Run:
    python main.py
"""

from web import run


if __name__ == "__main__":
    run()
