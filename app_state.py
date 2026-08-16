from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONFIG_ROOT_ENV = "SPOTDL_CONFIG_ROOT"
MUSIC_DIR_ENV = "SPOTDL_MUSIC_DIR"
DEFAULT_SYNC_INTERVAL_SECONDS = 3600


class StateStore:
    def __init__(self, config_root: Path | None = None):
        base = config_root or Path(os.getenv(CONFIG_ROOT_ENV, "."))
        self.config_root = Path(base).expanduser()
        self.config_root.mkdir(parents=True, exist_ok=True)

        self.config_path = self.config_root / "app-config.json"
        self.download_records_path = self.config_root / "download-records.json"
        self.scheduler_state_path = self.config_root / "scheduler-state.json"
        self.credentials_path = self.config_root / "credentials.json"

        self._config = self._load_json(self.config_path, self._default_config())
        self._records = self._load_json(self.download_records_path, {"downloaded": {}})
        self._scheduler_state = self._load_json(self.scheduler_state_path, {})

    def _default_config(self) -> dict[str, Any]:
        return {
            "setup_complete": False,
            "mp3_folder": "",
            "sync_interval_seconds": DEFAULT_SYNC_INTERVAL_SECONDS,
            "playlists": [],
        }

    def _load_json(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return default.copy()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {**default, **data}
        except (json.JSONDecodeError, OSError):
            pass
        return default.copy()

    def _save_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def set_config(self, config: dict[str, Any]) -> dict[str, Any]:
        self._config = {
            "setup_complete": bool(config.get("setup_complete", False)),
            "mp3_folder": str(config.get("mp3_folder") or ""),
            "sync_interval_seconds": int(config.get("sync_interval_seconds") or DEFAULT_SYNC_INTERVAL_SECONDS),
            "playlists": list(config.get("playlists") or []),
        }
        self._save_json(self.config_path, self._config)
        return self._config

    def config(self) -> dict[str, Any]:
        return dict(self._config)

    def set_setup(self, mp3_folder: str, sync_interval_seconds: int) -> dict[str, Any]:
        return self.set_config(
            {
                **self._config,
                "setup_complete": True,
                "mp3_folder": mp3_folder,
                "sync_interval_seconds": int(sync_interval_seconds),
            }
        )

    def set_playlists(self, playlists: list[dict[str, str]]) -> list[dict[str, str]]:
        updated = {**self._config, "playlists": playlists}
        self.set_config(updated)
        return list(playlists)

    def playlists(self) -> list[dict[str, str]]:
        return list(self._config.get("playlists") or [])

    def sync_interval_seconds(self) -> int:
        value = int(self._config.get("sync_interval_seconds") or DEFAULT_SYNC_INTERVAL_SECONDS)
        return max(1, value)

    def setup_required(self) -> bool:
        return not bool(self._config.get("setup_complete"))

    def resolve_music_dir_for(self, mp3_folder: str | None) -> Path:
        configured = str(mp3_folder or "").strip()
        if configured:
            path = Path(configured).expanduser()
            if not path.is_absolute():
                path = (self.config_root / path).resolve()
            return path

        return self._default_music_dir()

    def _default_music_dir(self) -> Path:
        env_value = str(os.getenv(MUSIC_DIR_ENV, "")).strip()
        if env_value:
            path = Path(env_value).expanduser()
            if not path.is_absolute():
                path = Path.cwd() / path
            return path
        return Path("downloads")

    def resolve_music_dir(self) -> Path:
        return self.resolve_music_dir_for(str(self._config.get("mp3_folder") or ""))

    def ensure_music_dir_writable(self) -> Path:
        return self.ensure_path_writable(self.resolve_music_dir())

    def ensure_music_dir_value_writable(self, mp3_folder: str) -> Path:
        return self.ensure_path_writable(self.resolve_music_dir_for(mp3_folder))

    def ensure_path_writable(self, target: Path) -> Path:
        if target.exists() and not target.is_dir():
            raise ValueError(f"Configured MP3 folder path is not a directory: {target}")
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".spotdl-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except OSError as exc:
            raise ValueError(f"Configured MP3 folder is not writable: {target} ({exc})") from exc
        return target

    def _save_records(self) -> None:
        self._save_json(self.download_records_path, self._records)

    def record_download(self, track_id: str, filename: str) -> None:
        downloaded = self._records.setdefault("downloaded", {})
        downloaded[track_id] = {
            "filename": filename,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_records()

    def is_downloaded(self, track_id: str) -> bool:
        return track_id in self._records.get("downloaded", {})

    def scheduler_state(self) -> dict[str, Any]:
        return dict(self._scheduler_state)

    def set_scheduler_state(self, updates: dict[str, Any]) -> dict[str, Any]:
        self._scheduler_state = {**self._scheduler_state, **updates}
        self._save_json(self.scheduler_state_path, self._scheduler_state)
        return dict(self._scheduler_state)
