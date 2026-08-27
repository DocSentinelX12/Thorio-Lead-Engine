from pathlib import Path


class RuntimeLock:
    """
    Prevents multiple Lead Engine processes from running
    the same local workload at the same time.
    """

    def __init__(self, path="data/engine.lock"):
        self.path = Path(path)
        self.acquired = False

    def acquire(self) -> bool:
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        try:
            self.path.open(
                "x",
                encoding="utf-8",
            ).close()
        except FileExistsError:
            return False

        self.acquired = True
        return True

    def release(self) -> bool:
        if not self.acquired:
            return False

        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

        self.acquired = False
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
