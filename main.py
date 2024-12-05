import os
import binascii
from libspot.proto import StorageResolve_pb2 as StorageResolve

from libspot.core import Session
from libspot.metadata import TrackId
from aiohttp import web
import requests

if os.path.isfile("credentials.json"):
    session = Session.Builder().stored_file().create()
else:
    print("No credentials.json file found.")
    exit()


def search_track(query: str):
    token = session.tokens().get("user-read-email")
    resp = requests.get(
        "https://api.spotify.com/v1/search",
        {"limit": "5", "offset": "0", "q": query, "type": "track"},
        headers={"Authorization": "Bearer %s" % token},
    )
    i = 1
    tracks = resp.json()["tracks"]["items"]
    return tracks[0]["id"]


def get_track(track_id: str, quality: str = "320"):
    if len(track_id) != 22:
        track_id = search_track(track_id)

    track_id = TrackId.from_base62(track_id)
    song = session.api().get_metadata_4_track(track_id)
    key = session.audio_key().get_audio_key(song.gid, song.file[0].file_id, True)
    resp = session.api().send(
        "GET",
        "/storage-resolve/files/audio/interactive/{}".format(
            binascii.hexlify(song.file[0].file_id).decode()
        ),
        None,
        None,
    )
    storage_resolve_response = StorageResolve.StorageResolveResponse()
    storage_resolve_response.ParseFromString(resp.content)
    return str(storage_resolve_response.cdnurl[0]), key, song.name, song.artist[0].name


async def get_track_handler(request):
    track_id = request.match_info.get("id")
    cdnurl, key, name, artist = get_track(track_id, 320)
    return web.json_response({"cdnurl": cdnurl, "key": key.hex(), "name": name, "artist": artist})


app = web.Application()
app.router.add_get("/get_track/{id}", get_track_handler)
web.run_app(app, host="0.0.0.0", port=5000)
