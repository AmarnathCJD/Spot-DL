import spotipy
from album_utils import download_album

def download_all_albums_by_artist(spotify_api_id, spotify_api_secret, artist, spotipy_module, args, config):
    sp = spotipy_module.Spotify(auth_manager=spotipy_module.SpotifyClientCredentials(
        client_id=spotify_api_id, client_secret=spotify_api_secret))
    # Search for the artist
    results = sp.search(q=f'artist:{artist}', type='artist', limit=1)
    items = results['artists']['items']
    if not items:
        print(f'Artist not found: {artist}')
        return
    artist_id = items[0]['id']
    # Get all albums by the artist
    albums = []
    seen = set()
    results = sp.artist_albums(artist_id, album_type='album')
    albums.extend(results['items'])
    while results['next']:
        results = sp.next(results)
        albums.extend(results['items'])
    # Remove duplicate albums by name
    unique_albums = []
    for album in albums:
        name = album['name']
        if name not in seen:
            seen.add(name)
            unique_albums.append(album)
    print(f"Found {len(unique_albums)} albums for artist '{artist}'")
    import toml
    album_sleep = float(config.get('album_sleep', 0))
    for album in unique_albums:
        # Fetch canonical album name from Spotify
        album_info = sp.album(album['id'])
        canonical_album_name = album_info['name']
        download_album(
            spotify_api_id,
            spotify_api_secret,
            artist,
            canonical_album_name,
            spotipy_module,
            args,
            config
        )
        if album_sleep > 0:
            print(f"Sleeping {album_sleep} seconds before next album...")
            from time import sleep
            sleep(album_sleep)
