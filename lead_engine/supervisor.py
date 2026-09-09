from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence


class SupervisorConfigurationError(ValueError):
    """Raised when the worker supervisor is configured unsafely or incompletely."""


@dataclass(frozen=True)
class SupervisorConfig:
    command: tuple[str, ...]
    heartbeat_file: Path
    heartbeat_interval_seconds: float = 15.0
    restart_delay_seconds: float = 1.0
    max_restart_delay_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not self.command:
            raise SupervisorConfigurationError("worker command is required")
        if self.heartbeat_interval_seconds <= 0:
            raise SupervisorConfigurationError("heartbeat interval must be positive")
        if self.restart_delay_seconds < 0:
            raise SupervisorConfigurationError("restart delay cannot be negative")
        if self.max_restart_delay_seconds < self.restart_delay_seconds:
            raise SupervisorConfigurationError("maximum restart delay must be >= restart delay")


class WorkerSupervisor:
    """Keep one worker alive, restart crashes, and expose a local heartbeat.

    This layer deliberately does not own credentials, browser storage, lead data,
    or partner delivery. It only supervises an already configured worker command.
    """

    def __init__(self, config: SupervisorConfig):
        self.config = config
        self._stopping = False
        self._child: Optional[subprocess.Popen[bytes]] = None

    def stop(self, *_args: object) -> None:
        self._stopping = True
        child = self._child
        if child is not None and child.poll() is None:
            child.terminate()

    def _heartbeat(self, state: str, restart_count: int) -> None:
        path = self.config.heartbeat_file
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        payload = (
            f"state={state}\n"
            f"pid={os.getpid()}\n"
            f"restart_count={restart_count}\n"
            f"timestamp={time.time():.6f}\n"
        )
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)

    def run(self) -> int:
        previous_handlers = {}
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, self.stop)

        restart_count = 0
        delay = self.config.restart_delay_seconds
        try:
            while not self._stopping:
                self._heartbeat("starting", restart_count)
                self._child = subprocess.Popen(list(self.config.command))
                while not self._stopping:
                    code = self._child.poll()
                    if code is not None:
                        break
                    self._heartbeat("running", restart_count)
                    time.sleep(self.config.heartbeat_interval_seconds)

                if self._stopping:
                    self.stop()
                    self._heartbeat("stopped", restart_count)
                    return 0

                restart_count += 1
                self._heartbeat("restarting", restart_count)
                time.sleep(delay)
                delay = min(
                    self.config.max_restart_delay_seconds,
                    max(self.config.restart_delay_seconds, delay * 2),
                )
        finally:
            for sig, handler in previous_handlers.items():
                signal.signal(sig, handler)
        return 0


def config_from_environment() -> SupervisorConfig:
    raw_command = os.getenv("THORIO_WORKER_COMMAND", "").strip()
    if not raw_command:
        raise SupervisorConfigurationError("THORIO_WORKER_COMMAND is required")
    command = tuple(part for part in raw_command.split(" ") if part)
    heartbeat = os.getenv("THORIO_SUPERVISOR_HEARTBEAT", "").strip()
    if not heartbeat:
        raise SupervisorConfigurationError("THORIO_SUPERVISOR_HEARTBEAT is required")
    return SupervisorConfig(
        command=command,
        heartbeat_file=Path(heartbeat).expanduser(),
        heartbeat_interval_seconds=float(os.getenv("THORIO_SUPERVISOR_HEARTBEAT_INTERVAL", "15")),
        restart_delay_seconds=float(os.getenv("THORIO_SUPERVISOR_RESTART_DELAY", "1")),
        max_restart_delay_seconds=float(os.getenv("THORIO_SUPERVISOR_MAX_RESTART_DELAY", "60")),
    )


def main() -> int:
    return WorkerSupervisor(config_from_environment()).run()


if __name__ == "__main__":
    raise SystemExit(main())
