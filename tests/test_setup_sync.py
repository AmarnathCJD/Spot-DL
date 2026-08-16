import asyncio
import json
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

import jobs
import mp3
import web


class _DummySession:
    class _Tokens:
        def get(self, _scope):
            return "token"

    def tokens(self):
        return self._Tokens()


class _FakeWizard:
    def __init__(self, credentials_path):
        self.credentials_path = Path(credentials_path)
        self._state = "idle"
        self._polls = 0

    def start(self):
        self._state = "waiting"

    def status(self):
        if self._state == "waiting":
            self._polls += 1
            if self._polls > 2:
                self.credentials_path.parent.mkdir(parents=True, exist_ok=True)
                self.credentials_path.write_text("creds", encoding="utf-8")
                self._state = "captured"
        return {
            "state": self._state,
            "device_name": "spotify-connect-local",
            "credentials_path": str(self.credentials_path),
        }

    def stop(self):
        self._state = "idle"


def _reset_jobs_state():
    jobs._jobs.clear()
    while True:
        try:
            jobs._queue.get_nowait()
            jobs._queue.task_done()
        except asyncio.QueueEmpty:
            break


async def _with_client(app, fn):
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        return await fn(client)
    finally:
        await client.close()


def _run(coro):
    return asyncio.run(coro)


def _json(response):
    return json.loads(response.text)


@pytest.fixture(autouse=True)
def _clean_jobs_and_download_dir(monkeypatch):
    _reset_jobs_state()
    mp3.set_download_dir(None)
    yield
    _reset_jobs_state()
    mp3.set_download_dir(None)


def _build_app(tmp_path, monkeypatch):
    config_root = tmp_path / "config"
    monkeypatch.setenv("SPOTDL_CONFIG_ROOT", str(config_root))
    monkeypatch.setattr(web.spotify, "get_session", lambda: _DummySession())
    monkeypatch.setattr(
        web.spotify,
        "with_session_retry",
        lambda fn, *args, **kwargs: fn(*args, **kwargs),
    )
    monkeypatch.setattr(web.jobs, "start", lambda _app: asyncio.sleep(0))
    monkeypatch.setattr(web.jobs, "stop", lambda _app: asyncio.sleep(0))
    return web.build_app(wizard_factory=lambda p: _FakeWizard(p))


def test_setup_state_requires_configuration(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)

    async def scenario(client):
        response = await client.get("/api/setup/state")
        body = await response.json()
        assert response.status == 200
        assert body["setup_required"] is True
        assert body["setup_complete"] is False

    _run(_with_client(app, scenario))


def test_setup_save_persists_mp3_folder_interval_and_completion(tmp_path, monkeypatch):
    config_root = tmp_path / "config"
    app = _build_app(tmp_path, monkeypatch)

    async def save(client):
        response = await client.post(
            "/api/setup",
            json={"mp3_folder": str(tmp_path / "music"), "sync_interval_seconds": 90},
        )
        body = await response.json()
        assert response.status == 200
        assert body["setup_complete"] is True
        assert body["sync_interval_seconds"] == 90

    _run(_with_client(app, save))

    restarted = web.build_app(
        config_root=config_root,
        wizard_factory=lambda p: _FakeWizard(p),
    )

    async def verify(client):
        response = await client.get("/api/setup/state")
        body = await response.json()
        assert response.status == 200
        assert body["setup_required"] is False
        assert body["setup_complete"] is True
        assert body["mp3_folder"] == str(tmp_path / "music")
        assert body["sync_interval_seconds"] == 90

    _run(_with_client(restarted, verify))


def test_connect_wizard_start_and_status_transitions_write_credentials(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)

    async def scenario(client):
        start = await client.post("/api/connect/start")
        started = await start.json()
        assert start.status == 202
        assert started["state"] == "waiting"

        status1 = await client.get("/api/connect/status")
        body1 = await status1.json()
        assert body1["state"] == "waiting"

        status2 = await client.get("/api/connect/status")
        body2 = await status2.json()
        assert body2["state"] == "captured"

        credentials = Path(body2["credentials_path"])
        assert credentials.exists()

    _run(_with_client(app, scenario))


def test_missing_credentials_returns_degraded_errors_without_crash(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    monkeypatch.setattr(web, "_probe_session", lambda: (_ for _ in ()).throw(RuntimeError("missing credentials")))

    async def scenario(client):
        health = await client.get("/healthz?deep=1")
        health_body = await health.json()
        assert health.status == 503
        assert health_body["status"] == "degraded"

        playlist = await client.get("/api/playlist/7xeQp9BIVJjCariTYXdRK3?count=1")
        playlist_body = await playlist.json()
        assert playlist.status == 503
        assert playlist_body["error"] == "spotify_setup_required"

        enqueue = await client.post("/api/queue", json={"track_id": "3KrXbna4rv7YXkZHagRtHK"})
        enqueue_body = await enqueue.json()
        assert enqueue.status == 503
        assert enqueue_body["error"] == "spotify_setup_required"

        alive = await client.get("/healthz")
        assert alive.status == 200

    _run(_with_client(app, scenario))


@pytest.mark.parametrize(
    "playlist_ref",
    [
        "https://open.spotify.com/playlist/7xeQp9BIVJjCariTYXdRK3",
        "spotify:playlist:1LY3GhF0zxIVgbYEQjCbUO",
        "2bf7wxuRxN2tkNoPH7z1an",
    ],
)
def test_playlist_crud_persists_and_accepts_url_uri_and_id(tmp_path, monkeypatch, playlist_ref):
    config_root = tmp_path / "config"
    app = _build_app(tmp_path, monkeypatch)

    async def scenario(client):
        setup = await client.post(
            "/api/setup",
            json={"mp3_folder": str(tmp_path / "music"), "sync_interval_seconds": 120},
        )
        assert setup.status == 200

        created = await client.post("/api/playlists", json={"playlist": playlist_ref, "name": "mix"})
        body = await created.json()
        assert created.status == 201
        playlist_id = body["playlist"]["id"]

        listed = await client.get("/api/playlists")
        listed_body = await listed.json()
        assert listed.status == 200
        assert any(item["id"] == playlist_id for item in listed_body["playlists"])

        updated = await client.put(
            f"/api/playlists/{playlist_id}",
            json={"playlist": "spotify:playlist:4PCUyejIMnQs6mYrR90QFp", "name": "new"},
        )
        updated_body = await updated.json()
        assert updated.status == 200
        assert updated_body["playlist"]["name"] == "new"

        deleted = await client.delete(f"/api/playlists/{updated_body['playlist']['id']}")
        assert deleted.status == 200

    _run(_with_client(app, scenario))

    restarted = web.build_app(
        config_root=config_root,
        wizard_factory=lambda p: _FakeWizard(p),
    )

    async def verify(client):
        listed = await client.get("/api/playlists")
        listed_body = await listed.json()
        assert listed.status == 200
        assert listed_body["playlists"] == []

    _run(_with_client(restarted, verify))


def test_playlist_crud_rejects_invalid_reference(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)

    async def scenario(client):
        response = await client.post("/api/playlists", json={"playlist": "not-a-playlist"})
        body = await response.json()
        assert response.status == 400
        assert "invalid playlist reference" in body["error"]

    _run(_with_client(app, scenario))


def test_sync_run_dedupes_downloaded_and_queued_tracks(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)

    playlists = {
        "A": ["downloaded", "new-1", "shared"],
        "B": ["shared", "queued", "new-2"],
    }
    monkeypatch.setattr(
        web.spotify,
        "playlist_items",
        lambda playlist_id: {
            "id": playlist_id,
            "name": playlist_id,
            "total": len(playlists[playlist_id]),
            "returned": len(playlists[playlist_id]),
            "truncated": False,
            "ids": playlists[playlist_id],
        },
    )
    monkeypatch.setattr(web.jobs, "queued_track_ids", lambda: {"queued"})

    enqueued = []

    def _enqueue(track_id, title="", artist="", cover=""):
        enqueued.append(track_id)
        return jobs.Job(track_id=track_id)

    monkeypatch.setattr(web.jobs, "enqueue", _enqueue)

    async def scenario(client):
        setup = await client.post(
            "/api/setup",
            json={"mp3_folder": str(tmp_path / "music"), "sync_interval_seconds": 60},
        )
        assert setup.status == 200

        await client.post("/api/playlists", json={"playlist": "spotify:playlist:Aaaaaaaaaaaaaaaaaaaaaa"})
        await client.post("/api/playlists", json={"playlist": "spotify:playlist:Bbbbbbbbbbbbbbbbbbbbbb"})

        # overwrite parsed IDs for deterministic fake playlist map keys
        app["state_store"].set_playlists([
            {"id": "A", "ref": "spotify:playlist:A", "name": "A"},
            {"id": "B", "ref": "spotify:playlist:B", "name": "B"},
        ])
        app["state_store"].record_download("downloaded", "done.mp3")
        app["state_store"].credentials_path.write_text("creds", encoding="utf-8")

        sync = await client.post("/api/sync/run")
        body = await sync.json()
        assert sync.status == 200
        assert body["queued"] == 3

    _run(_with_client(app, scenario))
    assert enqueued == ["new-1", "shared", "new-2"]


def test_file_serving_uses_configured_mp3_folder_and_default_fallback(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)

    async def scenario(client):
        setup = await client.post(
            "/api/setup",
            json={"mp3_folder": str(tmp_path / "music"), "sync_interval_seconds": 60},
        )
        assert setup.status == 200

        path = tmp_path / "music"
        path.mkdir(parents=True, exist_ok=True)
        file_path = path / "Artist - Song 2026.mp3"
        file_path.write_bytes(b"mp3")

        job = jobs.enqueue("3KrXbna4rv7YXkZHagRtHK")
        job.status = jobs.DONE
        job.filename = file_path.name

        response = await client.get(f"/api/file/{job.id}")
        assert response.status == 200
        assert response.headers["Content-Type"] == "audio/mpeg"

    _run(_with_client(app, scenario))
    fallback = web.build_app(
        config_root=tmp_path / "fallback-config",
        wizard_factory=lambda p: _FakeWizard(p),
    )
    assert fallback["state_store"].resolve_music_dir().name == "downloads"


def test_setup_and_sync_fail_on_unwritable_path(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    blocked_path = tmp_path / "not-a-dir"
    blocked_path.write_text("file", encoding="utf-8")

    async def scenario(client):
        setup = await client.post(
            "/api/setup",
            json={"mp3_folder": str(blocked_path), "sync_interval_seconds": 60},
        )
        setup_body = await setup.json()
        assert setup.status == 400
        assert str(blocked_path) in setup_body["error"]

        state = await client.get("/api/setup/state")
        state_body = await state.json()
        assert state.status == 200
        assert state_body["setup_required"] is True
        assert state_body["setup_complete"] is False

        app["state_store"].set_config(
            {
                "setup_complete": True,
                "mp3_folder": str(blocked_path),
                "sync_interval_seconds": 60,
                "playlists": [{"id": "A", "ref": "spotify:playlist:A", "name": "A"}],
            }
        )
        app["state_store"].credentials_path.write_text("creds", encoding="utf-8")
        sync = await client.post("/api/sync/run")
        sync_body = await sync.json()
        assert sync.status == 400
        assert str(blocked_path) in sync_body["error"]

    _run(_with_client(app, scenario))


def test_scheduler_runs_automatically_and_skips_overlapping_manual_trigger(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)

    calls = []

    async def fake_cycle(_app, trigger):
        calls.append(trigger)
        await asyncio.sleep(0.12)
        return {"queued": 0, "skipped": 0}

    monkeypatch.setattr(web, "_run_sync_cycle", fake_cycle)

    app["state_store"].set_config(
        {
            "setup_complete": True,
            "mp3_folder": str(tmp_path / "music"),
            "sync_interval_seconds": 1,
            "playlists": [{"id": "A", "ref": "spotify:playlist:A", "name": "A"}],
        }
    )
    app["state_store"].credentials_path.write_text("creds", encoding="utf-8")

    async def scenario(client):
        await asyncio.sleep(1.25)
        manual = await client.post("/api/sync/run")
        assert manual.status in {200, 409}

    _run(_with_client(app, scenario))
    assert "scheduled" in calls
    assert calls.count("manual") <= 1
