from __future__ import annotations

import binascii
import datetime
import logging
import os
import threading

import requests

from libspot.core import Session
from libspot.metadata import TrackId
from libspot.proto import StorageResolve_pb2 as StorageResolve

import audio

LOGGER = logging.getLogger("spot-dl-server")

SPCLIENT_UA = "Spotify/8.9.96.476 Android/34 (22101316I)"
CREDENTIALS_PATH = "credentials.json"


_session_mutex = threading.Lock()
_session: Session | None = None


def _build_session() -> Session:
    if not os.path.isfile(CREDENTIALS_PATH):
        raise RuntimeError(f"No {CREDENTIALS_PATH} file found.")
    return Session.Builder().stored_file(CREDENTIALS_PATH).create()


def get_session() -> Session:
    """Return the singleton librespot Session, building it on first call.

    Thread-safe. On a closed/dead session call reset_session() first.
    """
    global _session
    if _session is None:
        with _session_mutex:
            if _session is None:
                LOGGER.info("creating librespot session")
                _session = _build_session()
    return _session


def reset_session(reason: str = "") -> None:
    """Drop the cached session so the next get_session() rebuilds.

    Idempotent; close errors are swallowed because the session is already known-bad.
    """
    global _session
    with _session_mutex:
        if _session is not None:
            LOGGER.warning(f"resetting librespot session ({reason})")
            try:
                _session.close()
            except Exception:
                pass
            _session = None


_TRANSIENT_ERRORS = (
    ConnectionError, ConnectionResetError, ConnectionAbortedError,
    BrokenPipeError, TimeoutError, OSError,
)
_TRANSIENT_KEYWORDS = (
    "connection", "closed", "reset", "broken pipe", "eof", "timeout", "socket",
    "failed to receive packet", "session isn't authenticated",
)


def _looks_transient(e: BaseException) -> bool:
    if isinstance(e, _TRANSIENT_ERRORS):
        return True
    msg = str(e).lower()
    return any(s in msg for s in _TRANSIENT_KEYWORDS)


def with_session_retry(fn, *args, retries: int = 1, **kwargs):
    """Run fn(*args, **kwargs); on transport errors reset the session and retry.

    fn is expected to obtain its session via get_session() so the retry picks up
    a freshly built one.
    """
    last_exc: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if _looks_transient(e) and attempt < retries:
                last_exc = e
                reset_session(f"{type(e).__name__}: {e}")
                continue
            raise
    raise last_exc  # type: ignore[misc]


def _convert_ms(milliseconds: int) -> str:
    delta = datetime.timedelta(milliseconds=milliseconds)
    minutes = (delta.seconds // 60) % 60
    seconds = delta.seconds % 60
    ms = delta.microseconds // 1000
    return f"{minutes:02d}:{seconds:02d}.{ms:03d}"


def get_lyrics(track_id: str) -> tuple[str, tuple[int, int, int] | None]:
    """Fetch synced lyrics + Spotify's recommended background color.

    Returns (lrc_string, bg_color_rgb_tuple_or_None). Falls back to a placeholder
    LRC string when lyrics are unavailable; bg_color is None when the response
    omits the colors block.
    """
    token = get_session().tokens().get("user-read-playback-state")
    resp = requests.get(
        f"https://spclient.wg.spotify.com/color-lyrics/v2/track/{track_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": SPCLIENT_UA,
            "Accept": "application/json",
        },
        params={
            "vocalRemoval": "false",
            "syllableSync": "false",
            "clientLanguage": "en_IN",
        },
    )

    bg_color: tuple[int, int, int] | None = None
    try:
        data = resp.json()
        bg_int = data.get("colors", {}).get("background")
        if bg_int is not None:
            argb = bg_int & 0xFFFFFFFF
            bg_color = ((argb >> 16) & 0xFF, (argb >> 8) & 0xFF, argb & 0xFF)
    except (ValueError, AttributeError):
        pass

    try:
        lines = resp.json()["lyrics"]["lines"]
        synced = ""
        for line in lines:
            ts = _convert_ms(int(line["startTimeMs"]))
            synced += f"[{ts}]{line['words']}\n"
    except KeyError:
        synced = "You'd have to guess this one"

    return synced, bg_color


def _spclient_search(query: str, lim: int):
    token = get_session().tokens().get("user-read-email")
    resp = requests.get(
        "https://spclient.wg.spotify.com/searchview/km/v4/search/"
        + requests.utils.quote(query),
        params={
            "entityVersion": "2",
            "limit": str(lim),
            "catalogue": "premium",
            "country": get_session().country_code or "US",
            "locale": "en",
            "imageSize": "small",
        },
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": SPCLIENT_UA,
            "Accept": "application/json",
        },
    )
    return resp.json()["results"]["tracks"]["hits"]


def search_track_solo(query: str) -> str:
    """Return the top hit's track ID for a free-text query."""
    hits = _spclient_search(query, 1)
    return hits[0]["uri"].split(":")[-1]


def search_track(query: str, lim: int = 5) -> list[dict]:
    """Return up to `lim` track dicts: name, artist, id, year, cover, cover_small."""
    hits = _spclient_search(query, lim)
    results: list[dict] = []
    for hit in hits:
        try:
            cover = hit.get("image", "")
            results.append({
                "name": hit["name"],
                "artist": hit["artists"][0]["name"],
                "id": hit["uri"].split(":")[-1],
                "year": "",
                "cover": cover,
                "cover_small": cover,
            })
        except (KeyError, IndexError):
            pass
    return results


def _resolve_track_metadata(track_id: str) -> dict:
    """Fetch a single track's display metadata over Mercury.

    Returns {name, artist, id, year, cover}. Returns blanks on any failure
    so the caller can filter and still return partial playlist data.
    """
    try:
        tid = TrackId.from_base62(track_id)
        song = get_session().api().get_metadata_4_track(tid)
        cover = ""
        if song.album.cover_group.image and len(song.album.cover_group.image) > 2:
            cover = "https://i.scdn.co/image/" + binascii.hexlify(
                song.album.cover_group.image[2].file_id
            ).decode()
        year = ""
        if song.album.date.year:
            year = str(song.album.date.year)
        return {
            "name": song.name,
            "artist": song.artist[0].name if song.artist else "",
            "id": track_id,
            "year": year,
            "cover": cover,
        }
    except Exception as e:
        LOGGER.warning(f"metadata fetch failed for {track_id}: {e}")
        return {"name": "", "artist": "", "id": track_id, "year": "", "cover": ""}


def get_playlist(playlist_id: str) -> list[dict]:
    """Return a playlist's track list.

    Uses spclient.wg.spotify.com/playlist/v2 (Login5-token-friendly) for the
    track URI list, then resolves each track's display metadata over Mercury
    in parallel. The public Web API endpoint is rate-limited for librespot
    tokens, so we avoid it entirely.
    """
    from concurrent.futures import ThreadPoolExecutor

    token = get_session().tokens().get("user-read-email")
    resp = requests.get(
        f"https://spclient.wg.spotify.com/playlist/v2/playlist/{playlist_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": SPCLIENT_UA,
            "Accept": "application/json",
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"playlist/v2 {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    items = data.get("contents", {}).get("items", [])
    track_ids: list[str] = []
    for item in items:
        uri = item.get("uri", "")
        if uri.startswith("spotify:track:"):
            track_ids.append(uri.split(":")[-1])

    if not track_ids:
        return []

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_resolve_track_metadata, track_ids))
    return [r for r in results if r.get("name")]


def radio_seed(track_id: str, count: int = 10, exclude: list[str] | None = None) -> list[dict]:
    """Spotify-style radio station seeded from a track.

    Hits spclient.wg.spotify.com/radio-apollo/v3/stations/{uri} — same endpoint
    the mobile clients use to build "Song Radio". Returns [{id, uri}, ...]
    excluding the seed and any IDs passed in `exclude`.
    """
    token = get_session().tokens().get("user-read-email")
    prev = ",".join(exclude or [])
    resp = requests.get(
        f"https://spclient.wg.spotify.com/radio-apollo/v3/stations/spotify:track:{track_id}",
        params={"count": str(count), "prev_tracks": prev},
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": SPCLIENT_UA,
            "Accept": "application/json",
        },
    )
    if resp.status_code != 200:
        raise RuntimeError(f"radio-apollo {resp.status_code}: {resp.text[:200]}")
    tracks = resp.json().get("tracks", [])
    seed_uri = f"spotify:track:{track_id}"
    out: list[dict] = []
    for t in tracks:
        uri = t.get("uri", "")
        if not uri.startswith("spotify:track:") or uri == seed_uri:
            continue
        out.append({"id": uri.split(":")[-1], "uri": uri})
    return out


def get_track(track_id_or_query: str):
    """Resolve a track to (cdnurl, key, name, artist, tc, cover, lyrics, bg_color).

    Accepts either a 22-char base62 track ID or a free-text query (which is
    routed through search_track_solo first). The CDN URL is pre-signed and
    valid for ~1 hour.
    """
    if len(track_id_or_query) != 22:
        track_id_or_query = search_track_solo(track_id_or_query)

    track_id_str = track_id_or_query
    track_id_obj: TrackId = TrackId.from_base62(track_id_str)
    sess = get_session()
    song = sess.api().get_metadata_4_track(track_id_obj)

    cover_id = ""
    if song.album.cover_group.image and len(song.album.cover_group.image) > 2:
        cover_id = binascii.hexlify(song.album.cover_group.image[2].file_id).decode()

    key = sess.audio_key().get_audio_key(song.gid, song.file[0].file_id, True)
    resp = sess.api().send(
        "GET",
        "/storage-resolve/files/audio/interactive/{}".format(
            binascii.hexlify(song.file[0].file_id).decode()
        ),
        None,
        None,
    )
    sr = StorageResolve.StorageResolveResponse()
    sr.ParseFromString(resp.content)

    try:
        lyr, bg_color = get_lyrics(track_id_str)
    except Exception:
        lyr, bg_color = "You'd have to guess this one", None

    return (
        str(sr.cdnurl[0]),
        key,
        song.name,
        song.artist[0].name,
        track_id_str,
        "https://i.scdn.co/image/" + cover_id,
        lyr,
        bg_color,
    )


def fetch_audio_ogg(track_id: str):
    """Download + decrypt the audio for `track_id`. Returns (ogg_bytes, meta_dict)."""
    cdnurl, key, name, artist, tc, cover, lyrics, bg_color = get_track(track_id)
    enc = requests.get(cdnurl).content
    ogg = audio.decrypt_stream(enc, key)
    meta = {
        "name": name, "artist": artist, "tc": tc,
        "cover": cover, "lyrics": lyrics, "bg_color": bg_color,
    }
    return ogg, meta
