from typing import Any, Dict


class EngineLifecycle:
    """
    Tracks the lifecycle state of the lead engine.

    This is intentionally small and deterministic so it can
    later be used by a CLI, scheduler, service, or UI.
    """

    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"

    def __init__(self):
        self._state = self.STARTING

    @property
    def state(self) -> str:
        return self._state

    def start(self) -> Dict[str, Any]:
        self._state = self.RUNNING

        return self.snapshot()

    def stop(self) -> Dict[str, Any]:
        self._state = self.STOPPING
        snapshot = self.snapshot()

        self._state = self.STOPPED

        return {
            **snapshot,
            "state": self._state,
        }

    def snapshot(self) -> Dict[str, Any]:
        return {
            "state": self._state,
            "running": self._state == self.RUNNING,
            "stopped": self._state == self.STOPPED,
        }


if __name__ == "__main__":
    lifecycle = EngineLifecycle()

    print(lifecycle.start())
    print(lifecycle.stop())
