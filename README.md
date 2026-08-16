# Spot-DL

Spot-DL downloads Spotify tracks to tagged MP3 files through a web app.

## Features

- React UI + aiohttp backend.
- One-time setup flow before normal search/queue UI.
- Guided Spotify Connect credential capture (`spotify-connect-local`).
- Persistent playlist list with add, update, remove.
- Manual and scheduled sync with dedupe against queued/downloaded tracks.
- Configurable MP3 folder.
- Serial download worker (one track at a time).

## Local run

```bash
cd web && npm install && npm run build && cd ..
python main.py
```

Open `http://localhost:5555`.

## Docker

Build and run:

```bash
docker build -t spot-dl:local .
docker run --rm -p 5555:5555 \
  -e SPOTDL_CONFIG_ROOT=/config \
  -e SPOTDL_MUSIC_DIR=/music \
  -v "$PWD/spotdl-config:/config" \
  -v "$PWD/spotdl-music:/music" \
  spot-dl:local
```

The image is multi-stage and self-contained. It does not require a repo checkout inside the container.

### Synology/NAS notes

- Keep one HTTP port (`5555`), one config volume (`/config`), one music volume (`/music`).
- Spotify Connect discovery uses mDNS. If discovery fails with bridge networking, run host networking where your NAS allows it.

## Persistent data

Under `SPOTDL_CONFIG_ROOT`:

- `credentials.json`
- `app-config.json`
- `download-records.json`
- `scheduler-state.json`

MP3 files are written under `SPOTDL_MUSIC_DIR` (or setup-configured folder).
Each MP3 also gets a same-basename `.json` sidecar with populated Spotify
metadata resolved at download time.

Spotify FLAC/lossless export is not supported unless Spotify exposes an
official lossless source for the track. Requests for `format: "lossless"`,
`flac`, or `wav` are rejected before a job is queued rather than producing fake
lossless files from a lossy source.

## Setup flow

1. Open UI.
2. Save MP3 folder + sync interval.
3. Start Spotify Connect wizard and switch playback to `spotify-connect-local`.
4. Add playlists (URL, URI, or bare ID).
5. Run manual sync or wait for scheduled sync.

## Development checks

```bash
./.venv/bin/python -m pytest -q
cd web && npm run lint && npm run build
```

## Disclaimer

This project is for personal and educational use. It is not affiliated with Spotify.
