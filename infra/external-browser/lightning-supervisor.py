#!/usr/bin/env python3
"""Keep the Thorio browser and collection engine alive inside a Lightning Studio."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = Path(os.environ.get("THORIO_EXTERNAL_BROWSER_LOG_DIR", str(Path.home() / ".thorio" / "logs")))
LOG_DIR.mkdir(parents=True, exist_ok=True)
ENV_FILE = Path(os.environ.get("THORIO_EXTERNAL_BROWSER_ENV_FILE", str(Path.home() / ".thorio" / "engine.env")))


def _env() -> dict[str, str]:
    env = os.environ.copy()
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:].strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip("'").strip('"')
    env.setdefault("THORIO_BROWSER_PROFILE_DIR", str(Path.home() / ".thorio" / "browser-profile"))
    env.setdefault("THORIO_BROWSER_CDP_URL", "http://127.0.0.1:9222")
    env.setdefault("THORIO_BROWSER_CDP_PORT", "9222")
    env.setdefault("THORIO_BROWSER_HEADLESS", "1")
    env.setdefault("THORIO_FREE_ONLY", "1")
    env.setdefault("LEAD_ENGINE_DATA_DIR", str(ROOT / "data"))
    return env


def main() -> None:
    env = _env()
    stop = False
    children: dict[str, subprocess.Popen[str]] = {}

    def terminate(_signum: int, _frame: object) -> None:
        nonlocal stop
        stop = True
        for process in children.values():
            if process.poll() is None:
                process.terminate()

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)

    commands = {
        "browser": [sys.executable, str(ROOT / "infra" / "external-browser" / "browser-worker.py")],
        "engine": [sys.executable, "-m", "lead_engine.cli", "run-scheduled", "--interval", "60", "--forever"],
    }

    while not stop:
        for name, command in commands.items():
            process = children.get(name)
            if process is None or process.poll() is not None:
                log = (LOG_DIR / f"thorio-{name}.log").open("a", encoding="utf-8")
                children[name] = subprocess.Popen(
                    command,
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
        time.sleep(5)

    for process in children.values():
        if process.poll() is None:
            process.terminate()
    for process in children.values():
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    main()
