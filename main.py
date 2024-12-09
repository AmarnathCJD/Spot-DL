import os
import binascii
from libspot.proto import StorageResolve_pb2 as StorageResolve

from libspot.core import Session
from libspot.metadata import TrackId
from libspot.util import convert_milliseconds
from aiohttp import web
import requests

if os.path.isfile("credentials.json"):
    session = Session.Builder().stored_file().create()
else:
    print("No credentials.json file found.")
    exit()

def get_lyrics(track_id: str):
    token = session.tokens().get("user-read-playback-state")
    resp = requests.get(
        "https://spclient.wg.spotify.com/color-lyrics/v2/track/{}".format(track_id),
        headers={
            "Authorization": "Bearer %s" % token,
            "User-Agent": "Spotify/8.9.96.476 Android/34 (22101316I)",
            "Accept": "application/json",
        },
        params={
            "vocalRemoval": "false",
            "syllableSync": "false",
            "clientLanguage": "en_IN",
        },
    )

    try:
        synced_lyric = ""
        lines = resp.json()["lyrics"]["lines"]
        for line in lines:
            startms = int(line["startTimeMs"])
            words = line["words"]
            timeStamp = convert_milliseconds(startms)
            synced_lyric += f"[{timeStamp}]{words}\n"
    except KeyError:
        synced_lyric = "You'd have to guess this one"

    return synced_lyric

def search_track_solo(query: str):
    token = session.tokens().get("user-read-email")
    resp = requests.get(
        "https://api.spotify.com/v1/search",
        {"limit": "5", "offset": "0", "q": query, "type": "track"},
        headers={"Authorization": "Bearer %s" % token},
    )
    i = 1
    tracks = resp.json()["tracks"]["items"]
    return tracks[0]["id"]

def search_track(query: str):
    token = session.tokens().get("user-read-email")
    resp = requests.get(
        "https://api.spotify.com/v1/search",
        {"limit": "5", "offset": "0", "q": query, "type": "track"},
        headers={"Authorization": "Bearer %s" % token},
    )
    results = []
    for i in range(5):
        try:
            results.append({
                "name": resp.json()["tracks"]["items"][i]["name"],
                "artist": resp.json()["tracks"]["items"][i]["artists"][0]["name"],
                "id": resp.json()["tracks"]["items"][i]["id"],
                "year": resp.json()["tracks"]["items"][i]["album"]["release_date"][:4]
            })
        except:
            pass
    return results

def get_track(track_id: str, quality: str = "320"):
    if len(track_id) != 22:
        track_id = search_track_solo(track_id)

    track_id_str = track_id
    track_id: TrackId = TrackId.from_base62(track_id)
    song = session.api().get_metadata_4_track(track_id)
    cover_id = ""
    if song.album.cover_group.image and len(song.album.cover_group.image) > 2:
        cover_id = binascii.hexlify(song.album.cover_group.image[2].file_id).decode()
    # lr = get_lyrics(tc)
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
    try:
        lyr = get_lyrics(track_id_str)
    except:
        lyr = "You'd have to guess this one"

    return (
        str(storage_resolve_response.cdnurl[0]),
        key,
        song.name,
        song.artist[0].name,
        track_id_str,
        "https://i.scdn.co/image/" + cover_id,
        lyr,
    )


async def get_track_handler(request):
    track_id = request.match_info.get("id")
    try:
        cdnurl, key, name, artist, tc, cover, lyrics = get_track(track_id, 320)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)
    return web.json_response(
        {
            "cdnurl": cdnurl,
            "key": key.hex(),
            "name": name,
            "artist": artist,
            "tc": tc,
            "cover": cover,
            "lyrics": lyrics,
        }
    )

async def search_track_handler(request):
    query = request.match_info.get("query")
    try:
        results = search_track(query)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)
    return web.json_response(
        {
            "results": results
        }
    )

app = web.Application()
app.router.add_get("/get_track/{id}", get_track_handler)
app.router.add_get("/search_track/{query}", search_track_handler)
web.run_app(app, host="0.0.0.0", port=5000)
