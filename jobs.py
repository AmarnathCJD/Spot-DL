from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import mp3
import spotify

LOGGER = logging.getLogger("spot-dl-server")

QUEUED = "queued"
DONE = "done"
ERROR = "error"
REMOVABLE = frozenset({QUEUED, DONE, ERROR})


@dataclass
class Job:
    track_id: str
    title: str = ""
    artist: str = ""
    cover: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = QUEUED
    error: str = ""
    filename: str = ""
    created_at: float = field(default_factory=time.time)


_jobs: "OrderedDict[str, Job]" = OrderedDict()
_queue: asyncio.Queue[str] = asyncio.Queue()
_download_dir_getter: Callable[[], Path] = mp3.download_dir
_done_callback: Callable[[Job], None] | None = None


def enqueue(track_id: str, title: str = "", artist: str = "", cover: str = "") -> Job:
    job = Job(track_id=track_id, title=title, artist=artist, cover=cover)
    _jobs[job.id] = job
    _queue.put_nowait(job.id)
    return job


def snapshot() -> list[dict]:
    return [asdict(j) for j in _jobs.values()]


def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def remove(job_id: str) -> bool:
    """Drop a finished or still-queued job from the registry.

    An in-flight job is never dropped: cancelling mid-download would leave the
    mp3 on disk unreachable through `/api/file`. A queued job keeps its slot in
    the asyncio queue; the worker skips IDs it can no longer resolve.
    """
    job = _jobs.get(job_id)
    if job is None or job.status not in REMOVABLE:
        return False
    del _jobs[job_id]
    return True


def file_path(job_id: str) -> Path | None:
    job = _jobs.get(job_id)
    if not job or job.status != DONE or not job.filename:
        return None
    path = _download_dir_getter() / job.filename
    return path if path.exists() else None


async def _run(job: Job) -> None:
    job.status = "downloading"
    ogg, meta = await asyncio.to_thread(
        spotify.with_session_retry, spotify.fetch_audio_ogg, job.track_id
    )
    job.title = meta.get("name") or job.title
    job.artist = meta.get("artist") or job.artist
    job.cover = meta.get("cover") or job.cover

    job.status = "converting"
    data = await asyncio.to_thread(mp3.encode_mp3, ogg)

    job.status = "tagging"
    cover = await asyncio.to_thread(mp3.fetch_cover, meta.get("cover", ""))
    path = await asyncio.to_thread(mp3.write_tagged, data, meta, cover, _download_dir_getter())

    job.filename = path.name
    job.status = DONE
    if _done_callback is not None:
        _done_callback(job)


def queued_track_ids() -> set[str]:
    return {
        j.track_id
        for j in _jobs.values()
        if j.status in {QUEUED, "downloading", "converting", "tagging"}
    }


def set_download_dir_getter(getter: Callable[[], Path]) -> None:
    global _download_dir_getter
    _download_dir_getter = getter


def set_done_callback(callback: Callable[[Job], None] | None) -> None:
    global _done_callback
    _done_callback = callback


async def worker() -> None:
    """Serial download worker: one track at a time, failures never stop the queue."""
    while True:
        job_id = await _queue.get()
        job = _jobs.get(job_id)
        if job is None:
            _queue.task_done()
            continue
        try:
            await _run(job)
            LOGGER.info(f"job {job.id} done: {job.filename}")
        except asyncio.CancelledError:
            job.status = QUEUED
            raise
        except Exception as e:
            job.status = ERROR
            job.error = f"{type(e).__name__}: {e}"[:300]
            LOGGER.exception(f"job {job.id} failed: {job.error}")
        finally:
            _queue.task_done()


async def start(app) -> None:
    app["download_worker"] = asyncio.create_task(worker())


async def stop(app) -> None:
    task = app.get("download_worker")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
