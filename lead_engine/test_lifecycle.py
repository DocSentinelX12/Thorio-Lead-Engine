from .lifecycle import EngineLifecycle


def test_lifecycle_starts_in_starting_state():
    lifecycle = EngineLifecycle()

    assert lifecycle.state == EngineLifecycle.STARTING


def test_lifecycle_can_start():
    lifecycle = EngineLifecycle()

    result = lifecycle.start()

    assert lifecycle.state == EngineLifecycle.RUNNING
    assert result["state"] == EngineLifecycle.RUNNING
    assert result["running"] is True
    assert result["stopped"] is False


def test_lifecycle_can_stop():
    lifecycle = EngineLifecycle()

    lifecycle.start()

    result = lifecycle.stop()

    assert lifecycle.state == EngineLifecycle.STOPPED
    assert result["state"] == EngineLifecycle.STOPPED
    assert result["running"] is False
    assert result["stopped"] is True
