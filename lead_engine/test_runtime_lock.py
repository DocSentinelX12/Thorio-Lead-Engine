from .runtime_lock import RuntimeLock


def test_runtime_lock_can_be_acquired(tmp_path):
    lock = RuntimeLock(
        str(tmp_path / "engine.lock")
    )

    assert lock.acquire() is True
    assert lock.acquired is True

    assert lock.release() is True
    assert lock.acquired is False


def test_runtime_lock_blocks_second_process(tmp_path):
    path = str(tmp_path / "engine.lock")

    first = RuntimeLock(path)
    second = RuntimeLock(path)

    assert first.acquire() is True
    assert second.acquire() is False

    first.release()

    assert second.acquire() is True
    second.release()


def test_runtime_lock_context_manager(tmp_path):
    path = str(tmp_path / "engine.lock")

    with RuntimeLock(path) as lock:
        assert lock.acquired is True

    assert lock.acquired is False
    assert not (tmp_path / "engine.lock").exists()
