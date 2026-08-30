import os
from pathlib import Path

import fcntl


class RuntimeLock:
    """
    Prevents multiple Lead Engine processes from running
    the same local workload at the same time.

    Uses an OS-level advisory lock so the lock is automatically
    released if the owning process crashes or is terminated.
    """

    def __init__(self, path="data/engine.lock"):
        self.path = Path(path)
        self._file = None
        self.acquired = False

    def acquire(self) -> bool:
        if self.acquired:
            return True

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        file_handle = self.path.open(
            "a+",
            encoding="utf-8",
        )

        try:
            fcntl.flock(
                file_handle.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,
            )
        except BlockingIOError:
            file_handle.close()
            return False
        except Exception:
            file_handle.close()
            raise

        file_handle.seek(0)
        file_handle.truncate()
        file_handle.write(
            f"pid={os.getpid()}\n"
        )
        file_handle.flush()

        self._file = file_handle
        self.acquired = True
        return True

    def release(self) -> bool:
        if not self.acquired:
            return False

        file_handle = self._file
        self._file = None
        self.acquired = False

        if file_handle is None:
            return False

        try:
            fcntl.flock(
                file_handle.fileno(),
                fcntl.LOCK_UN,
            )
        finally:
            file_handle.close()

        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

        return True

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError(
                "Lead Engine is already running."
            )

        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        self.release()
