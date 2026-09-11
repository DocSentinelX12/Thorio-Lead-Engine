from unittest.mock import MagicMock

from .scheduler import LeadScheduler


def test_scheduler_allows_configured_collection_capacity(monkeypatch):
    monkeypatch.setenv("THORIO_SOURCE_COLLECTION_WORKERS", "64")
    scheduler = LeadScheduler(runner=MagicMock())
    assert scheduler._collection_workers() == 64


def test_scheduler_caps_collection_capacity(monkeypatch):
    monkeypatch.setenv("THORIO_SOURCE_COLLECTION_WORKERS", "9999")
    scheduler = LeadScheduler(runner=MagicMock())
    assert scheduler._collection_workers() == 64
