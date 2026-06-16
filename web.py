from __future__ import annotations

import asyncio
import logging
import re

from aiohttp import web

import spotify
import video

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
LOGGER = logging.getLogger("spot-dl-server")


def _safe_filename(s: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", s).strip() or "track"


def _error_payload(e: Exception) -> dict:
    return {"error": f"{type(e).__name__}: {e}" if str(e) else type(e).__name__}


async def get_track_handler(request: web.Request) -> web.Response:
    track_id = request.match_info.get("id")
    LOGGER.info(f"new-/get_track-request: {track_id}")
    try:
        cdnurl, key, name, artist, tc, cover, lyrics, bg_color = await asyncio.to_thread(
            spotify.with_session_retry, spotify.get_track, track_id
        )
    except Exception as e:
        LOGGER.exception(f"/get_track failed: {type(e).__name__}: {e}")
        return web.json_response(_error_payload(e), status=500)
    return web.json_response({
        "cdnurl": cdnurl,
        "key": key.hex(),
        "name": name,
        "artist": artist,
        "tc": tc,
        "cover": cover,
        "lyrics": lyrics,
        "bg_color": list(bg_color) if bg_color else None,
    })


async def search_track_handler(request: web.Request) -> web.Response:
    """Legacy positional-arg form: GET /search_track/{query}?lim=5."""
    query = request.match_info.get("query")
    lim = request.query.get("lim", 5)
    LOGGER.info(f"new-/search_track-request: {query}")
    try:
        results = await asyncio.to_thread(
            spotify.with_session_retry, spotify.search_track, query, int(lim)
        )
    except Exception as e:
        return web.json_response(_error_payload(e), status=500)
    return web.json_response({"results": results})


async def get_playlist_handler(request: web.Request) -> web.Response:
    playlist_id = request.match_info.get("id")
    LOGGER.info(f"new-/get_playlist-request: {playlist_id}")
    try:
        results = await asyncio.to_thread(
            spotify.with_session_retry, spotify.get_playlist, playlist_id
        )
    except Exception as e:
        LOGGER.exception(f"/get_playlist failed: {type(e).__name__}: {e}")
        return web.json_response(_error_payload(e), status=500)
    return web.json_response({"results": results})


async def track_audio_handler(request: web.Request) -> web.Response:
    track_id = request.match_info.get("id")
    LOGGER.info(f"new-/track-request: {track_id}")
    try:
        ogg, meta = await asyncio.to_thread(
            spotify.with_session_retry, spotify.fetch_audio_ogg, track_id
        )
    except Exception as e:
        LOGGER.exception(f"/track failed: {type(e).__name__}: {e}")
        return web.json_response(_error_payload(e), status=500)
    fname = f"{_safe_filename(meta['name'])} - {_safe_filename(meta['artist'])}.ogg"
    return web.Response(
        body=ogg,
        headers={
            "Content-Type": "audio/ogg",
            "Content-Disposition": f'attachment; filename="{fname}"',
            "X-Track-Name": meta["name"],
            "X-Track-Artist": meta["artist"],
        },
    )


async def track_video_handler(request: web.Request) -> web.StreamResponse:
    track_id = request.match_info.get("id")
    LOGGER.info(f"new-/vtrack-request: {track_id}")
    try:
        ogg, meta = await asyncio.to_thread(
            spotify.with_session_retry, spotify.fetch_audio_ogg, track_id
        )
    except Exception as e:
        LOGGER.exception(f"/vtrack failed: {type(e).__name__}: {e}")
        return web.json_response(_error_payload(e), status=500)

    fname = f"{_safe_filename(meta['name'])} - {_safe_filename(meta['artist'])}.mp4"
    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "video/mp4",
            "Content-Disposition": f'inline; filename="{fname}"',
            "X-Track-Name": meta["name"],
            "X-Track-Artist": meta["artist"],
            "Cache-Control": "no-store",
        },
    )
    resp.enable_chunked_encoding()
    await resp.prepare(request)
    try:
        async for chunk in video.build_video_stream(ogg, meta):
            await resp.write(chunk)
    except (ConnectionResetError, asyncio.CancelledError):
        LOGGER.info("client disconnected mid-stream")
    await resp.write_eof()
    return resp


async def search_handler(request: web.Request) -> web.Response:
    query = request.query.get("q", "").strip()
    lim = int(request.query.get("lim", 5))
    if not query:
        return web.json_response({"error": "missing ?q="}, status=400)
    LOGGER.info(f"new-/search-request: {query}")
    try:
        results = await asyncio.to_thread(
            spotify.with_session_retry, spotify.search_track, query, lim
        )
        return web.json_response({"results": results})
    except Exception as e:
        return web.json_response(_error_payload(e), status=500)


async def radio_handler(request: web.Request) -> web.Response:
    """GET /radio/{id}?count=10&exclude=id1,id2 → JSON list of next tracks."""
    track_id = request.match_info.get("id")
    count = int(request.query.get("count", 10))
    exclude_param = request.query.get("exclude", "")
    exclude = [x.strip() for x in exclude_param.split(",") if x.strip()] if exclude_param else []
    LOGGER.info(f"new-/radio-request: seed={track_id} count={count} exclude={len(exclude)}")
    try:
        tracks = await asyncio.to_thread(
            spotify.with_session_retry, spotify.radio_seed, track_id, count, exclude,
        )
        return web.json_response({"tracks": tracks})
    except Exception as e:
        return web.json_response(_error_payload(e), status=500)


async def index(request: web.Request) -> web.Response:
    return web.Response(text=(
        "Spot-DL API\n"
        "  GET /healthz                     -> liveness/readiness probe\n"
        "  GET /search?q=<query>&lim=5      -> JSON search results\n"
        "  GET /track/{id}                  -> audio/ogg (decrypted)\n"
        "  GET /vtrack/{id}                 -> video/mp4 1080p H.264 (lyrics + audio + waveform)\n"
        "  GET /radio/{id}?count=10         -> JSON list of recommended tracks\n"
        "  GET /get_track/{id}              -> JSON (cdnurl + key, legacy)\n"
        "  GET /get_playlist/{id}           -> JSON playlist\n"
    ))


def _probe_session() -> bool:
    """Cheap call that proves the librespot session is alive (or rebuilds it)."""
    tok = spotify.with_session_retry(
        lambda: spotify.get_session().tokens().get("user-read-email")
    )
    return bool(tok)


async def healthz(request: web.Request) -> web.Response:
    """Liveness (default) or readiness (?deep=1).

    Readiness wraps the probe in a 5s wait so a hung session can't wedge it;
    on failure the session is reset and we return 503.
    """
    deep = request.query.get("deep", "0") == "1"
    if not deep:
        return web.json_response({"status": "ok", "session": spotify._session is not None})
    try:
        ok = await asyncio.wait_for(asyncio.to_thread(_probe_session), timeout=5.0)
    except (asyncio.TimeoutError, Exception) as e:
        spotify.reset_session(f"healthz: {type(e).__name__}")
        return web.json_response(
            {"status": "degraded", "error": str(e)[:200]}, status=503
        )
    return web.json_response({"status": "ok", "session": True, "probed": ok})


def build_app() -> web.Application:
    """Wire the routes and return the aiohttp Application."""
    app = web.Application(client_max_size=64 * 1024 * 1024)
    app.router.add_get("/", index)
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/search", search_handler)
    app.router.add_get("/radio/{id}", radio_handler)
    app.router.add_get("/track/{id}", track_audio_handler)
    app.router.add_get("/vtrack/{id}", track_video_handler)
    app.router.add_get("/get_track/{id}", get_track_handler)
    app.router.add_get("/search_track/{query}", search_track_handler)
    app.router.add_get("/get_playlist/{id}", get_playlist_handler)
    return app


def run(host: str = "0.0.0.0", port: int = 5000) -> None:
    """Eagerly build the librespot session, then serve the app on (host, port)."""
    spotify.get_session()
    web.run_app(build_app(), host=host, port=port)


if __name__ == "__main__":
    run()
