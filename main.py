import datetime
import os
import binascii
from libspot.proto import StorageResolve_pb2 as StorageResolve

from libspot.core import Session
from libspot.metadata import TrackId
from aiohttp import web
import requests
import logging
import argparse
import spotipy
import toml
from album_utils import download_album

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logging.getLogger("aiohttp").setLevel(logging.WARNING)
LOGGER = logging.getLogger("spot-dl-server")

if os.path.isfile("credentials.json"):
    session = Session.Builder().stored_file().create()
else:
    print("No credentials.json file found.")
    exit()


def convert_milliseconds(milliseconds):
    delta = datetime.timedelta(milliseconds=milliseconds)
    # hours = delta.seconds // 3600
    minutes = (delta.seconds // 60) % 60
    seconds = delta.seconds % 60
    milliseconds = delta.microseconds // 1000

    formatted_time = "{:02d}:{:02d}.{:03d}".format(minutes, seconds, milliseconds)

    return formatted_time

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


def search_track(query: str, lim: int = 5):
    token = session.tokens().get("user-read-email")
    resp = requests.get(
        "https://api.spotify.com/v1/search",
        {"limit": "{}".format(lim), "offset": "0", "q": query, "type": "track"},
        headers={"Authorization": "Bearer %s" % token},
    )
    results = []
    for i in range(lim):
        try:
            results.append(
                {
                    "name": resp.json()["tracks"]["items"][i]["name"],
                    "artist": resp.json()["tracks"]["items"][i]["artists"][0]["name"],
                    "id": resp.json()["tracks"]["items"][i]["id"],
                    "year": resp.json()["tracks"]["items"][i]["album"]["release_date"][
                        :4
                    ],
                    "cover": resp.json()["tracks"]["items"][i]["album"]["images"][0][
                        "url"
                    ],
                    "cover_small": resp.json()["tracks"]["items"][i]["album"]["images"][
                        2
                    ]["url"],
                }
            )
        except:
            pass
    return results


def get_playlist(playlist_id: str):
    token = session.tokens().get("user-read-email")
    resp = requests.get(
        "https://api.spotify.com/v1/playlists/{}".format(playlist_id),
        headers={"Authorization": "Bearer %s" % token},
    )
    tracks = resp.json()["tracks"]["items"]
    playlist = []

    for track in tracks:
        if track["track"]["name"] == "":
            continue
        try:
            cover = track["track"]["album"]["images"][0]["url"]
        except:
            cover = ""
        playlist.append(
            {
                "name": track["track"]["name"],
                "artist": track["track"]["artists"][0]["name"],
                "id": track["track"]["id"],
                "year": track["track"]["album"]["release_date"][:4],
                "cover": cover,
            }
        )
    return playlist


def get_track(track_id: str):
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
    LOGGER.info(f"new-track-request: {track_id}")

    try:
        cdnurl, key, name, artist, tc, cover, lyrics = get_track(track_id)
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
    lim = request.query.get("lim", 5)

    LOGGER.info(f"new-search-request: {query}")
    try:
        results = search_track(query, int(lim))
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)
    return web.json_response({"results": results})


async def get_playlist_handler(request):
    playlist_id = request.match_info.get("id")
    LOGGER.info(f"new-playlist-request: {playlist_id}")
    try:
        results = get_playlist(playlist_id)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)
    return web.json_response({"results": results})

async def index(request):
    return web.Response(text="Welcome to Spot-DL Server! Use /get_track/{id} or /search_track/{query} to interact with the API.")

def extract_spotify_id_from_url(url):
    import re
    # Match /artist/<id> or /album/<id>
    match = re.search(r'spotify\.com/(artist|album)/([a-zA-Z0-9]+)', url)
    if match:
        return match.group(1), match.group(2)
    return None, None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--album', type=str, help='Spotify album name to download')
    parser.add_argument('-A', '--artist', type=str, help='Spotify artist name for album search. Downloads the entire discography if no album name is passed')
    parser.add_argument('-u', '--url', type=str, help='Spotify album or artist URL')
    parser.add_argument('-x', '--audio-format', type=str, choices=['ogg', 'mp3'], default='ogg', help='Audio format to save (ogg or mp3)')
    args = parser.parse_args()

    config = toml.load('config.toml')
    spotify_api_id = config.get('spotify_api_id')
    spotify_api_secret = config.get('spotify_api_secret')

    if args.url:
        url_type, spotify_id = extract_spotify_id_from_url(args.url)
        if url_type == 'artist':
            from artist_utils import download_all_albums_by_artist
            # Use spotipy to get artist name from ID
            sp = spotipy.Spotify(auth_manager=spotipy.SpotifyClientCredentials(client_id=spotify_api_id, client_secret=spotify_api_secret))
            artist_info = sp.artist(spotify_id)
            artist_name = artist_info['name']
            download_all_albums_by_artist(spotify_api_id, spotify_api_secret, artist_name, spotipy, args, config)
            exit(0)
        elif url_type == 'album':
            # Use spotipy to get album and artist name from ID
            sp = spotipy.Spotify(auth_manager=spotipy.SpotifyClientCredentials(client_id=spotify_api_id, client_secret=spotify_api_secret))
            album_info = sp.album(spotify_id)
            album_name = album_info['name']
            artist_name = album_info['artists'][0]['name']
            download_album(spotify_api_id, spotify_api_secret, artist_name, album_name, spotipy, args, config)
            exit(0)
        else:
            print('Invalid or unsupported Spotify URL.')
            exit(1)

    if args.album and args.artist:
        download_album(spotify_api_id, spotify_api_secret, args.artist, args.album, spotipy, args, config)
        exit(0)
    elif args.artist:
        from artist_utils import download_all_albums_by_artist
        download_all_albums_by_artist(spotify_api_id, spotify_api_secret, args.artist, spotipy, args, config)
        exit(0)

    app = web.Application()
    app.router.add_get("/get_track/{id}", get_track_handler)
    app.router.add_get("/search_track/{query}", search_track_handler)
    app.router.add_get("/get_playlist/{id}", get_playlist_handler)
    app.router.add_get("/", index)
    web.run_app(app, host="0.0.0.0", port=5000)

if __name__ == "__main__":
    main()
