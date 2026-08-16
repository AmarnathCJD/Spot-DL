import asyncio
import json

import web


class Request:
    def __init__(self, body=None, match_info=None):
        self._body = body or {}
        self.match_info = match_info or {}

    async def json(self):
        return self._body


def payload(response):
    return json.loads(response.text)


def test_enqueue_rejects_spotify_lossless_before_queuing(monkeypatch):
    def fail_enqueue(*_args, **_kwargs):
        raise AssertionError("lossless requests must not enqueue")

    monkeypatch.setattr(web.jobs, "enqueue", fail_enqueue)

    response = asyncio.run(web.enqueue_handler(Request({
        "track_id": "3KrXbna4rv7YXkZHagRtHK",
        "format": "lossless",
    })))

    assert response.status == 422
    assert payload(response) == {
        "error": "Spotify Lossless export is not supported; this app writes MP3 files plus same-basename metadata JSON sidecars."
    }


def test_job_file_handler_keeps_mp3_response_contract(monkeypatch, tmp_path):
    path = tmp_path / "Artist - Song 2026.mp3"
    path.write_bytes(b"mp3")
    monkeypatch.setattr(web.jobs, "file_path", lambda job_id: path if job_id == "job-1" else None)

    response = asyncio.run(web.job_file_handler(Request(match_info={"job_id": "job-1"})))

    assert response.headers["Content-Type"] == "audio/mpeg"
    assert response.headers["Content-Disposition"] == 'attachment; filename="Artist - Song 2026.mp3"'
