#!/usr/bin/env python3
"""Run the persistent headless Chromium session used by Thorio browser collection.

The browser profile lives on the persistent external Linux node. The process
never opens a graphical UI and never exposes CDP beyond localhost. Thorio's
normal authenticated browser flow attaches over the local CDP endpoint.
"""

from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def _storage_state_path() -> Path | None:
    value = os.environ.get("THORIO_BROWSER_STORAGE_STATE_PATH", "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _port() -> int:
    raw = os.environ.get("THORIO_BROWSER_CDP_PORT", "9222").strip()
    try:
        port = int(raw)
    except ValueError as exc:
        raise RuntimeError("THORIO_BROWSER_CDP_PORT must be an integer") from exc
    if not 1024 <= port <= 65535:
        raise RuntimeError("THORIO_BROWSER_CDP_PORT must be between 1024 and 65535")
    return port


def run() -> None:
    storage_state = _storage_state_path()
    port = _port()
    stop_event = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--remote-debugging-address=127.0.0.1",
                f"--remote-debugging-port={port}",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--no-first-run",
            ],
        )
        context = browser.new_context(
            storage_state=str(storage_state) if storage_state and storage_state.exists() else None,
        )
        try:
            print(
                "THORIO BROWSER WORKER READY: ephemeral Chromium with persisted "
                f"authenticated state={storage_state}; CDP=http://127.0.0.1:{port}",
                flush=True,
            )
            while not stop_event.wait(30):
                pass
        finally:
            if storage_state:
                context.storage_state(path=str(storage_state), indexed_db=True)
                print(
                    f"THORIO BROWSER STATE SAVED: {storage_state}",
                    flush=True,
                )
            context.close()
            browser.close()


if __name__ == "__main__":
    run()
