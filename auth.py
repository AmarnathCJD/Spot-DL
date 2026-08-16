from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable

from libspot.zeroconf import ZeroconfServer

LOGGER = logging.getLogger("spot-dl-server")


class ConnectWizardSession:
    def __init__(
        self,
        credentials_path: Path,
        device_name: str = "spotify-connect-local",
        server_factory: Callable[[], object] | None = None,
    ):
        self.credentials_path = Path(credentials_path)
        self.device_name = device_name
        self._server_factory = server_factory or (lambda: ZeroconfServer.Builder().create())
        self._status_lock = threading.Lock()
        self._status = "idle"
        self._error = ""
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def _set_status(self, status: str, error: str = "") -> None:
        with self._status_lock:
            self._status = status
            self._error = error

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._set_status("waiting")
        self._thread = threading.Thread(target=self._run_capture, daemon=True)
        self._thread.start()

    def _run_capture(self) -> None:
        server = None
        try:
            self.credentials_path.parent.mkdir(parents=True, exist_ok=True)
            server = self._server_factory()
            while not self._stop_event.is_set():
                if self.credentials_path.exists():
                    self._set_status("captured")
                    return

                legacy_path = Path("credentials.json")
                if legacy_path.exists() and legacy_path.resolve() != self.credentials_path.resolve():
                    self.credentials_path.write_bytes(legacy_path.read_bytes())
                    self._set_status("captured")
                    return
                time.sleep(1)
        except Exception as exc:  # pragma: no cover - runtime safety net
            self._set_status("error", str(exc))
            LOGGER.exception("spotify connect capture failed: %s", exc)
        finally:
            close_fn = getattr(server, "close", None)
            if callable(close_fn):
                try:
                    close_fn()
                except Exception:
                    pass

    def stop(self) -> None:
        self._stop_event.set()

    def status(self) -> dict:
        with self._status_lock:
            return {
                "state": self._status,
                "device_name": self.device_name,
                "credentials_path": str(self.credentials_path),
                "error": self._error,
            }


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    wizard = ConnectWizardSession(Path("credentials.json"))
    logging.warning(
        "Transfer playback from desktop client to spotify-connect-local via Spotify Connect in order to store session"
    )
    wizard.start()
    while True:
        state = wizard.status()
        if state["state"] == "captured":
            logging.warning("Session stored in credentials.json. Now you can Ctrl+C")
            break
        if state["state"] == "error":
            raise RuntimeError(state["error"])
        time.sleep(1)


if __name__ == "__main__":
    main()
