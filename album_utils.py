import os
import re
import requests
from audio_utils import process_audio

def get_album_tracks(album_id: str, session):
    token = session.tokens().get("user-read-email")
    resp = requests.get(
        f"https://api.spotify.com/v1/albums/{album_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    data = resp.json()
    if "tracks" not in data or "items" not in data["tracks"]:
        print("Error: Unexpected album response format or invalid album ID.")
        print("Response:", data)
        return []
    tracks = data["tracks"]["items"]
    return [track["id"] for track in tracks]


def find_album_tracks(spotify_id, spotify_secret, artist, album, spotipy):
    sp = spotipy.Spotify(auth_manager=spotipy.SpotifyClientCredentials(
        client_id=spotify_id, client_secret=spotify_secret))
    results = sp.search(q=f'artist:{artist} album:{album}', type='album', limit=1)
    items = results['albums']['items']
    if not items:
        print('Album not found')
        return []
    album_id = items[0]['id']
    album_info = sp.album(album_id)
    return [track['id'] for track in album_info['tracks']['items']]


def process_track(tid, args, config, album_name=None):
    track_sleep = float(config.get('track_sleep', 5))
    from main import get_track  # Import here to avoid circular import at module level
    cdnurl, key, name, artist, tc, cover, lyrics = get_track(tid)
    print(f"Downloaded: {name} by {artist}")
    tmp_dir = config.get('tmp_path', './tmp')
    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir)
    safe_name = re.sub(r'[^a-zA-Z0-9 _\-]', '', name)
    safe_artist = re.sub(r'[^a-zA-Z0-9 _\-]', '', artist)
    # Use album_name if provided, else fallback to args.album
    album_for_path = album_name if album_name is not None else args.album
    safe_album = re.sub(r'[^a-zA-Z0-9 _\-]', '', album_for_path) if album_for_path else 'Unknown_Album'
    out_dir = f"{tmp_dir}/{safe_artist}/{safe_album}"

    # Make the tmp directory if it doesn't exist
    if not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    # Prepare filenames
    enc_filename = f"{out_dir}/encrypted - {safe_artist} - {safe_name}.ogg"
    dec_filename = f"{out_dir}/{safe_name}.ogg"

    try:
        audio_resp = requests.get(cdnurl, stream=True)
        audio_resp.raise_for_status()
        with open(enc_filename, "wb") as f:
            for chunk in audio_resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        print(f"Saved to {enc_filename}")
    except Exception as e:
        print(f"Error downloading audio: {e}")
        return
    try:
        process_audio(enc_filename, dec_filename, key.hex(), args.audio_format)
    except Exception as e:
        print(f"Error processing audio: {e}")
    if track_sleep > 0:
        print(f"Sleeping for {track_sleep} seconds...")
        from time import sleep
        sleep(track_sleep)

def download_album(spotify_api_id, spotify_api_secret, artist, album, spotipy, args, config):
    track_ids = find_album_tracks(spotify_api_id, spotify_api_secret, artist, album, spotipy)
    print(f"Downloading {len(track_ids)} tracks from album '{album}' by '{artist}'...")
    for tid in track_ids:
        try:
            process_track(tid, args, config, album_name=album)
        except Exception as e:
            print(f"Failed to download track {tid}: {e}")
    from filesystem_utils import move_artist_folder
    move_artist_folder(artist, config)


