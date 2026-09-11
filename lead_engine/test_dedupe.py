from .database import LeadDB
from .dedupe import Dedupe
from .models import Lead


def test_observation_persistence_does_not_business_dedupe(tmp_path):
    db = LeadDB(data_dir=str(tmp_path))
    dedupe = Dedupe(db)
    first = Lead(source="test", source_id="same", url="https://example.com/same", company="Acme", signal="remote engineer", evidence="opening", discovered_at="2026-01-01T00:00:00+00:00")
    second = Lead(source="test", source_id="same", url="https://example.com/same", company="Acme", signal="remote engineer", evidence="opening", discovered_at="2026-01-01T00:00:01+00:00")
    assert dedupe.accept(first) is True
    assert dedupe.accept(second) is True
    assert db.stats()[0] == 2
