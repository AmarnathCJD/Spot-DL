from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from aiohttp import web

import auth
import jobs
import mp3
import spotify
import video
from app_state import DEFAULT_SYNC_INTERVAL_SECONDS, StateStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logging.getLogger("aiohttp").setLevel(logging.WARNING)
LOGGER = logging.getLogger("spot-dl-server")

DIST = Path("web/dist")


def _safe_filename(s: str) -> str:
    return mp3.safe_component(s) or "track"


def _error_payload(e: Exception) -> dict:
    return {"error": f"{type(e).__name__}: {e}" if str(e) else type(e).__name__}


def _audio_format_error(value: object) -> web.Response | None:
    try:
        mp3.normalize_audio_format(value)
    except mp3.UnsupportedLosslessExport as e:
        return web.json_response({"error": str(e)}, status=422)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return None


def _state_store(request: web.Request) -> StateStore | None:
    app = getattr(request, "app", None)
    if app is None:
        return None
    return app.get("state_store")


def _spotify_setup_response(detail: str) -> web.Response:
    return web.json_response(
        {"error": "spotify_setup_required", "detail": detail}, status=503
    )


async def _ensure_spotify_credentials(request: web.Request) -> web.Response | None:
    store = _state_store(request)
    if store is None:
        return None
    if not store.credentials_path.exists():
        return _spotify_setup_response(
            f"Missing Spotify credentials at {store.credentials_path}. Run setup first."
        )
    return None


def _spotify_unavailable_response(exc: Exception) -> web.Response:
    return web.json_response(
        {"error": "spotify_setup_required", "detail": str(exc)[:300]}, status=503
    )


def _parse_playlist_ref(text: str) -> tuple[str, str]:
    ref = spotify.parse_spotify_ref(text, bare_as="playlist")
    if not ref or ref[0] != "playlist":
        raise ValueError("invalid playlist reference")
    return ref


def _playlist_name(playlist: dict, fallback: str = "") -> str:
    if playlist.get("name"):
        return str(playlist["name"])
    if fallback:
        return fallback
    return playlist.get("id", "")


async def get_track_handler(request: web.Request) -> web.Response:
    setup_error = await _ensure_spotify_credentials(request)
    if setup_error is not None:
        return setup_error

    track_id = request.match_info.get("id")
    LOGGER.info(f"new-/get_track-request: {track_id}")
    try:
        cdnurl, key, name, artist, tc, cover, lyrics, bg_color = await asyncio.to_thread(
            spotify.with_session_retry, spotify.get_track, track_id
        )
    except Exception as e:
        LOGGER.exception(f"/get_track failed: {type(e).__name__}: {e}")
        return _spotify_unavailable_response(e)
    return web.json_response(
        {
            "cdnurl": cdnurl,
            "key": key.hex(),
            "name": name,
            "artist": artist,
            "tc": tc,
            "cover": cover,
            "lyrics": lyrics,
            "bg_color": list(bg_color) if bg_color else None,
        }
    )


async def search_track_handler(request: web.Request) -> web.Response:
    setup_error = await _ensure_spotify_credentials(request)
    if setup_error is not None:
        return setup_error

    query = request.match_info.get("query")
    lim = request.query.get("lim", 5)
    LOGGER.info(f"new-/search_track-request: {query}")
    try:
        results = await asyncio.to_thread(
            spotify.with_session_retry, spotify.search_track, query, int(lim)
        )
    except Exception as e:
        return _spotify_unavailable_response(e)
    return web.json_response({"results": results})


async def get_playlist_handler(request: web.Request) -> web.Response:
    setup_error = await _ensure_spotify_credentials(request)
    if setup_error is not None:
        return setup_error

    playlist_id = request.match_info.get("id")
    LOGGER.info(f"new-/get_playlist-request: {playlist_id}")
    try:
        results = await asyncio.to_thread(
            spotify.with_session_retry, spotify.get_playlist, playlist_id
        )
    except Exception as e:
        LOGGER.exception(f"/get_playlist failed: {type(e).__name__}: {e}")
        return _spotify_unavailable_response(e)
    return web.json_response({"results": results})


async def track_audio_handler(request: web.Request) -> web.Response:
    setup_error = await _ensure_spotify_credentials(request)
    if setup_error is not None:
        return setup_error

    track_id = request.match_info.get("id")
    LOGGER.info(f"new-/track-request: {track_id}")
    try:
        ogg, meta = await asyncio.to_thread(
            spotify.with_session_retry, spotify.fetch_audio_ogg, track_id
        )
    except Exception as e:
        LOGGER.exception(f"/track failed: {type(e).__name__}: {e}")
        return _spotify_unavailable_response(e)
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
    setup_error = await _ensure_spotify_credentials(request)
    if setup_error is not None:
        return setup_error

    track_id = request.match_info.get("id")
    LOGGER.info(f"new-/vtrack-request: {track_id}")
    try:
        ogg, meta = await asyncio.to_thread(
            spotify.with_session_retry, spotify.fetch_audio_ogg, track_id
        )
    except Exception as e:
        LOGGER.exception(f"/vtrack failed: {type(e).__name__}: {e}")
        return _spotify_unavailable_response(e)

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

    setup_error = await _ensure_spotify_credentials(request)
    if setup_error is not None:
        return setup_error

    LOGGER.info(f"new-/search-request: {query}")
    try:
        results = await asyncio.to_thread(
            spotify.with_session_retry, spotify.search_track, query, lim
        )
        return web.json_response({"results": results})
    except Exception as e:
        return _spotify_unavailable_response(e)


async def radio_handler(request: web.Request) -> web.Response:
    setup_error = await _ensure_spotify_credentials(request)
    if setup_error is not None:
        return setup_error

    track_id = request.match_info.get("id")
    count = int(request.query.get("count", 10))
    exclude_param = request.query.get("exclude", "")
    exclude = [x.strip() for x in exclude_param.split(",") if x.strip()] if exclude_param else []
    LOGGER.info(f"new-/radio-request: seed={track_id} count={count} exclude={len(exclude)}")
    try:
        tracks = await asyncio.to_thread(
            spotify.with_session_retry, spotify.radio_seed, track_id, count, exclude
        )
        return web.json_response({"tracks": tracks})
    except Exception as e:
        return _spotify_unavailable_response(e)


async def enqueue_handler(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)

    track_id = body.get("track_id")
    if not isinstance(track_id, str) or not track_id.strip():
        return web.json_response({"error": "missing track_id"}, status=400)

    response = _audio_format_error(body.get("format"))
    if response is not None:
        return response

    setup_error = await _ensure_spotify_credentials(request)
    if setup_error is not None:
        return setup_error

    track_id = track_id.strip()
    try:
        await asyncio.wait_for(asyncio.to_thread(_probe_session), timeout=5.0)
    except Exception as exc:
        return _spotify_unavailable_response(exc)

    job = jobs.enqueue(
        track_id,
        title=body.get("title", ""),
        artist=body.get("artist", ""),
        cover=body.get("cover", ""),
    )
    LOGGER.info(f"queued job {job.id} for {track_id}")
    return web.json_response({"job": jobs.asdict(job)}, status=201)


async def batch_enqueue_handler(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)

    tracks = body.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        return web.json_response({"error": "missing tracks"}, status=400)

    setup_error = await _ensure_spotify_credentials(request)
    if setup_error is not None:
        return setup_error

    try:
        await asyncio.wait_for(asyncio.to_thread(_probe_session), timeout=5.0)
    except Exception as exc:
        return _spotify_unavailable_response(exc)

    valid_tracks = []
    batch_format = body.get("format")
    for track in tracks:
        if not isinstance(track, dict):
            continue
        track_id = track.get("track_id") or track.get("id")
        if not isinstance(track_id, str) or not track_id.strip():
            continue
        response = _audio_format_error(track.get("format", batch_format))
        if response is not None:
            return response
        valid_tracks.append(
            (
                track_id.strip(),
                track.get("title") or track.get("name", ""),
                track.get("artist", ""),
                track.get("cover", ""),
            )
        )

    created = [
        jobs.asdict(jobs.enqueue(track_id, title=title, artist=artist, cover=cover))
        for track_id, title, artist, cover in valid_tracks
    ]
    if not created:
        return web.json_response({"error": "no valid track_id in tracks"}, status=400)
    LOGGER.info(f"queued {len(created)} jobs from a batch of {len(tracks)}")
    return web.json_response({"jobs": created}, status=201)


async def playlist_handler(request: web.Request) -> web.Response:
    setup_error = await _ensure_spotify_credentials(request)
    if setup_error is not None:
        return setup_error

    playlist_id = request.match_info.get("id")
    ref = spotify.parse_spotify_ref(playlist_id or "", bare_as="playlist")
    if ref and ref[0] == "playlist":
        playlist_id = ref[1]
    try:
        count = int(request.query.get("count", 0))
    except ValueError:
        return web.json_response({"error": "count must be a number"}, status=400)

    LOGGER.info(f"new-/api/playlist-request: {playlist_id} count={count}")
    try:
        preview = await asyncio.to_thread(
            spotify.with_session_retry, spotify.playlist_preview, playlist_id, count
        )
    except Exception as e:
        LOGGER.exception(f"/api/playlist failed: {type(e).__name__}: {e}")
        return _spotify_unavailable_response(e)
    return web.json_response(preview)


async def queue_handler(request: web.Request) -> web.Response:
    return web.json_response({"jobs": jobs.snapshot()})


async def dequeue_handler(request: web.Request) -> web.Response:
    job_id = request.match_info.get("job_id")
    job = jobs.get(job_id)
    if job is None:
        return web.json_response({"error": "unknown job"}, status=404)
    if not jobs.remove(job_id):
        return web.json_response(
            {"error": f"job is {job.status}, wait for it to finish"}, status=409
        )
    return web.json_response({"removed": job_id})


async def job_file_handler(request: web.Request) -> web.StreamResponse:
    job_id = request.match_info.get("job_id")
    path = jobs.file_path(job_id)
    if path is None:
        return web.json_response({"error": "file not ready"}, status=404)
    return web.FileResponse(
        path,
        headers={
            "Content-Type": "audio/mpeg",
            "Content-Disposition": f'attachment; filename="{path.name}"',
        },
    )


async def setup_state_handler(request: web.Request) -> web.Response:
    store = request.app["state_store"]
    cfg = store.config()
    return web.json_response(
        {
            "setup_required": store.setup_required(),
            "setup_complete": bool(cfg.get("setup_complete")),
            "mp3_folder": cfg.get("mp3_folder") or "",
            "sync_interval_seconds": int(
                cfg.get("sync_interval_seconds") or DEFAULT_SYNC_INTERVAL_SECONDS
            ),
            "playlists": list(cfg.get("playlists") or []),
            "credentials_path": str(store.credentials_path),
        }
    )


async def setup_save_handler(request: web.Request) -> web.Response:
    store = request.app["state_store"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)

    mp3_folder = str(body.get("mp3_folder") or "").strip()
    if not mp3_folder:
        return web.json_response({"error": "mp3_folder is required"}, status=400)

    interval = body.get("sync_interval_seconds", DEFAULT_SYNC_INTERVAL_SECONDS)
    try:
        interval = int(interval)
    except (TypeError, ValueError):
        return web.json_response({"error": "sync_interval_seconds must be a positive integer"}, status=400)
    if interval <= 0:
        return web.json_response({"error": "sync_interval_seconds must be a positive integer"}, status=400)

    try:
        store.ensure_music_dir_value_writable(mp3_folder)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)

    existing = store.playlists()
    cfg = store.set_setup(mp3_folder, interval)
    if existing:
        store.set_playlists(existing)

    _apply_runtime_paths(request.app)
    return web.json_response(
        {
            "setup_complete": True,
            "mp3_folder": cfg["mp3_folder"],
            "sync_interval_seconds": int(cfg["sync_interval_seconds"]),
        }
    )


async def connect_start_handler(request: web.Request) -> web.Response:
    wizard = request.app["connect_wizard"]
    wizard.start()
    return web.json_response(wizard.status(), status=202)


async def connect_status_handler(request: web.Request) -> web.Response:
    wizard = request.app["connect_wizard"]
    return web.json_response(wizard.status())


async def playlists_list_handler(request: web.Request) -> web.Response:
    store = request.app["state_store"]
    return web.json_response({"playlists": store.playlists()})


async def playlists_add_handler(request: web.Request) -> web.Response:
    store = request.app["state_store"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)

    playlist_ref = str(body.get("playlist") or "").strip()
    name = str(body.get("name") or "").strip()
    try:
        _, playlist_id = _parse_playlist_ref(playlist_ref)
    except ValueError:
        return web.json_response({"error": "invalid playlist reference"}, status=400)

    playlists = store.playlists()
    if any(entry["id"] == playlist_id for entry in playlists):
        return web.json_response({"error": "playlist already exists"}, status=409)

    playlist = {"id": playlist_id, "ref": playlist_ref, "name": name or playlist_id}
    store.set_playlists(playlists + [playlist])
    return web.json_response({"playlist": playlist}, status=201)


async def playlists_update_handler(request: web.Request) -> web.Response:
    store = request.app["state_store"]
    playlist_id = request.match_info.get("playlist_id", "")

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)

    playlist_ref = str(body.get("playlist") or "").strip()
    name = str(body.get("name") or "").strip()
    if not playlist_ref:
        return web.json_response({"error": "playlist is required"}, status=400)

    try:
        _, next_id = _parse_playlist_ref(playlist_ref)
    except ValueError:
        return web.json_response({"error": "invalid playlist reference"}, status=400)

    playlists = store.playlists()
    found = False
    updated: list[dict[str, str]] = []
    for playlist in playlists:
        if playlist["id"] != playlist_id:
            updated.append(playlist)
            continue
        found = True
        updated.append({"id": next_id, "ref": playlist_ref, "name": name or _playlist_name(playlist, next_id)})

    if not found:
        return web.json_response({"error": "playlist not found"}, status=404)

    ids = [entry["id"] for entry in updated]
    if len(ids) != len(set(ids)):
        return web.json_response({"error": "playlist already exists"}, status=409)

    store.set_playlists(updated)
    current = next(entry for entry in updated if entry["id"] == next_id)
    return web.json_response({"playlist": current})


async def playlists_delete_handler(request: web.Request) -> web.Response:
    store = request.app["state_store"]
    playlist_id = request.match_info.get("playlist_id", "")
    playlists = store.playlists()
    kept = [item for item in playlists if item["id"] != playlist_id]
    if len(kept) == len(playlists):
        return web.json_response({"error": "playlist not found"}, status=404)
    store.set_playlists(kept)
    return web.json_response({"removed": playlist_id})


async def _run_sync_cycle(app: web.Application, trigger: str) -> dict:
    store: StateStore = app["state_store"]
    store.ensure_music_dir_writable()

    playlists = store.playlists()
    if not playlists:
        return {"queued": 0, "skipped_downloaded": 0, "skipped_queued": 0, "tracks": 0}

    seen: set[str] = set()
    ordered_ids: list[str] = []
    for playlist in playlists:
        listing = await asyncio.to_thread(
            spotify.with_session_retry, spotify.playlist_items, playlist["id"]
        )
        for track_id in listing.get("ids", []):
            if track_id in seen:
                continue
            seen.add(track_id)
            ordered_ids.append(track_id)

    queued_ids = jobs.queued_track_ids() if hasattr(jobs, "queued_track_ids") else {
        j.get("track_id") for j in jobs.snapshot() if j.get("status") in {"queued", "downloading", "converting", "tagging"}
    }

    queued = 0
    skipped_downloaded = 0
    skipped_queued = 0
    for track_id in ordered_ids:
        if store.is_downloaded(track_id):
            skipped_downloaded += 1
            continue
        if track_id in queued_ids:
            skipped_queued += 1
            continue
        jobs.enqueue(track_id)
        queued_ids.add(track_id)
        queued += 1

    now = datetime.now(timezone.utc).isoformat()
    store.set_scheduler_state(
        {
            "last_trigger": trigger,
            "last_run_at": now,
            "last_track_count": len(ordered_ids),
            "last_queued": queued,
        }
    )
    return {
        "queued": queued,
        "skipped_downloaded": skipped_downloaded,
        "skipped_queued": skipped_queued,
        "tracks": len(ordered_ids),
    }


async def sync_run_handler(request: web.Request) -> web.Response:
    setup_error = await _ensure_spotify_credentials(request)
    if setup_error is not None:
        return setup_error

    lock: asyncio.Lock = request.app["sync_lock"]
    if lock.locked():
        return web.json_response({"error": "sync already running"}, status=409)

    async with lock:
        try:
            payload = await _run_sync_cycle(request.app, trigger="manual")
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except Exception as exc:
            LOGGER.exception("manual sync failed: %s", exc)
            return _spotify_unavailable_response(exc)

    return web.json_response(payload)


async def _scheduler_loop(app: web.Application) -> None:
    try:
        while True:
            interval = max(1, app["state_store"].sync_interval_seconds())
            await asyncio.sleep(interval)

            store: StateStore = app["state_store"]
            if store.setup_required() or not store.playlists() or not store.credentials_path.exists():
                continue

            lock: asyncio.Lock = app["sync_lock"]
            if lock.locked():
                continue

            async with lock:
                try:
                    await _run_sync_cycle(app, trigger="scheduled")
                except Exception as exc:
                    LOGGER.warning("scheduled sync skipped: %s", exc)
    except asyncio.CancelledError:
        raise


async def scheduler_start(app: web.Application) -> None:
    app["scheduler_task"] = asyncio.create_task(_scheduler_loop(app))


async def scheduler_stop(app: web.Application) -> None:
    task = app.get("scheduler_task")
    if not task:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def spa(request: web.Request) -> web.StreamResponse:
    index = DIST / "index.html"
    if not index.exists():
        return web.Response(
            text="UI not built. Run: cd web && npm install && npm run build",
            status=503,
        )
    return web.FileResponse(index)


async def index(request: web.Request) -> web.Response:
    return web.Response(
        text=(
            "Spot-DL API\n"
            "  GET  /healthz                     -> liveness/readiness probe\n"
            "  GET  /api/setup/state             -> setup state\n"
            "  POST /api/setup                   -> save setup config\n"
            "  POST /api/connect/start           -> start Spotify Connect wizard\n"
            "  GET  /api/connect/status          -> wizard status\n"
            "  GET  /api/playlists               -> list configured playlists\n"
            "  POST /api/playlists               -> add configured playlist\n"
            "  PUT  /api/playlists/{id}          -> update configured playlist\n"
            "  DEL  /api/playlists/{id}          -> remove configured playlist\n"
            "  POST /api/sync/run                -> trigger a sync now\n"
            "  GET  /search?q=<query>&lim=5      -> JSON search results\n"
            "  POST /api/queue                   -> enqueue {track_id} for mp3 download\n"
            "  POST /api/queue/batch             -> enqueue {tracks:[{track_id}]} in one call\n"
            "  GET  /api/queue                   -> JSON queue state\n"
            "  DEL  /api/queue/{job_id}          -> drop a job from the queue\n"
            "  GET  /api/file/{job_id}           -> audio/mpeg (tagged 320kbps mp3)\n"
            "  GET  /api/playlist/{id}?count=N   -> playlist name, total, and its first N tracks\n"
            "  GET /track/{id}                  -> audio/ogg (decrypted)\n"
            "  GET /vtrack/{id}                 -> video/mp4 1080p H.264 (lyrics + audio + waveform)\n"
            "  GET /radio/{id}?count=10         -> JSON list of recommended tracks\n"
            "  GET /get_track/{id}              -> JSON (cdnurl + key, legacy)\n"
            "  GET /get_playlist/{id}           -> JSON playlist\n"
        )
    )


def _probe_session() -> bool:
    token = spotify.with_session_retry(
        lambda: spotify.get_session().tokens().get("user-read-email")
    )
    return bool(token)


async def healthz(request: web.Request) -> web.Response:
    deep = request.query.get("deep", "0") == "1"
    if not deep:
        return web.json_response({"status": "ok", "session": spotify._session is not None})

    try:
        ok = await asyncio.wait_for(asyncio.to_thread(_probe_session), timeout=5.0)
    except (asyncio.TimeoutError, Exception) as e:
        spotify.reset_session(f"healthz: {type(e).__name__}")
        return web.json_response({"status": "degraded", "error": str(e)[:200]}, status=503)
    return web.json_response({"status": "ok", "session": True, "probed": ok})


def _apply_runtime_paths(app: web.Application) -> None:
    store: StateStore = app["state_store"]
    spotify.CREDENTIALS_PATH = str(store.credentials_path)
    mp3.set_download_dir(store.resolve_music_dir())
    jobs.set_download_dir_getter(store.resolve_music_dir)

    def _record_download(job: jobs.Job) -> None:
        if job.filename:
            store.record_download(job.track_id, job.filename)

    jobs.set_done_callback(_record_download)


def build_app(
    config_root: Path | None = None,
    wizard_factory: Callable[[Path], object] | None = None,
) -> web.Application:
    app = web.Application(client_max_size=64 * 1024 * 1024)
    store = StateStore(config_root=config_root)
    wizard_builder = wizard_factory or (lambda path: auth.ConnectWizardSession(path))

    app["state_store"] = store
    app["connect_wizard"] = wizard_builder(store.credentials_path)
    app["sync_lock"] = asyncio.Lock()
    _apply_runtime_paths(app)

    app.router.add_get("/", spa)
    app.router.add_get("/api", index)
    app.router.add_get("/healthz", healthz)

    app.router.add_get("/api/setup/state", setup_state_handler)
    app.router.add_post("/api/setup", setup_save_handler)
    app.router.add_post("/api/connect/start", connect_start_handler)
    app.router.add_get("/api/connect/status", connect_status_handler)

    app.router.add_get("/api/playlists", playlists_list_handler)
    app.router.add_post("/api/playlists", playlists_add_handler)
    app.router.add_put("/api/playlists/{playlist_id}", playlists_update_handler)
    app.router.add_delete("/api/playlists/{playlist_id}", playlists_delete_handler)
    app.router.add_post("/api/sync/run", sync_run_handler)

    app.router.add_get("/search", search_handler)
    app.router.add_post("/api/queue", enqueue_handler)
    app.router.add_post("/api/queue/batch", batch_enqueue_handler)
    app.router.add_get("/api/queue", queue_handler)
    app.router.add_delete("/api/queue/{job_id}", dequeue_handler)
    app.router.add_get("/api/file/{job_id}", job_file_handler)
    app.router.add_get("/api/playlist/{id}", playlist_handler)
    app.router.add_get("/radio/{id}", radio_handler)
    app.router.add_get("/track/{id}", track_audio_handler)
    app.router.add_get("/vtrack/{id}", track_video_handler)
    app.router.add_get("/get_track/{id}", get_track_handler)
    app.router.add_get("/search_track/{query}", search_track_handler)
    app.router.add_get("/get_playlist/{id}", get_playlist_handler)

    if (DIST / "assets").is_dir():
        app.router.add_static("/assets", DIST / "assets")

    app.on_startup.append(jobs.start)
    app.on_startup.append(scheduler_start)
    app.on_cleanup.append(scheduler_stop)
    app.on_cleanup.append(jobs.stop)

    async def _stop_wizard(_app: web.Application) -> None:
        stop_fn = getattr(_app.get("connect_wizard"), "stop", None)
        if callable(stop_fn):
            stop_fn()

    app.on_cleanup.append(_stop_wizard)
    return app


def run(host: str = "0.0.0.0", port: int = 5555) -> None:
    web.run_app(build_app(), host=host, port=port)


if __name__ == "__main__":
    run()
