from .runtime_lock import RuntimeLock


def test_runtime_lock_is_released_after_context(
    tmp_path,
):
    path = str(
        tmp_path / "engine.lock"
    )

    with RuntimeLock(path):
        assert (
            tmp_path / "engine.lock"
        ).exists()

    assert not (
        tmp_path / "engine.lock"
    ).exists()


def test_runtime_lock_can_be_reacquired(
    tmp_path,
):
    path = str(
        tmp_path / "engine.lock"
    )

    first = RuntimeLock(path)

    assert first.acquire() is True
    assert first.release() is True

    second = RuntimeLock(path)

    assert second.acquire() is True
    assert second.release() is True


def test_failed_acquisition_does_not_release_owner_lock(
    tmp_path,
):
    path = str(
        tmp_path / "engine.lock"
    )

    owner = RuntimeLock(path)
    contender = RuntimeLock(path)

    assert owner.acquire() is True
    assert contender.acquire() is False

    assert (
        tmp_path / "engine.lock"
    ).exists()

    owner.release()

    assert not (
        tmp_path / "engine.lock"
    ).exists()
