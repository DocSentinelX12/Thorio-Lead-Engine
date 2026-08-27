from .database import LeadDB
from .dedupe import Dedupe
from .models import Lead


def test_duplicate_lead_is_rejected(tmp_path):
    db = LeadDB(
        data_dir=str(tmp_path)
    )

    dedupe = Dedupe(db)

    lead_one = Lead(
        source="test",
        source_id="duplicate-001",
        url="https://example.com/jobs/duplicate-001",
        company="Acme",
        signal="remote software engineer",
        evidence="Remote software engineer opening found.",
    )

    lead_two = Lead(
        source="test",
        source_id="duplicate-001",
        url="https://example.com/jobs/duplicate-001",
        company="Acme",
        signal="remote software engineer",
        evidence="Remote software engineer opening found.",
    )

    first_accepted = dedupe.accept(lead_one)
    second_accepted = dedupe.accept(lead_two)

    assert first_accepted is True
    assert second_accepted is False

    stats = db.stats()

    assert stats[0] == 1
