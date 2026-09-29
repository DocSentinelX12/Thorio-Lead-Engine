from .free_sources import FreeJobSource


def test_high_value_commercial_triggers_are_captured():
    triggers = (
        "looking for a development partner",
        "need an mvp",
        "need ai integration",
        "llm integration",
        "engineering staff augmentation",
        "cloud migration",
        "legacy modernization",
        "raised series a",
        "new enterprise customer",
        "product launch",
        "acquired",
    )
    for trigger in triggers:
        assert FreeJobSource._has_b2b_signal(trigger), trigger


def test_generic_unrelated_text_is_not_promoted_as_a_b2b_signal():
    assert not FreeJobSource._has_b2b_signal(
        "We are celebrating our annual company picnic."
    )


def test_high_value_commercial_link_is_collected():
    html = b"""
    <html>
      <a href="/services/ai-integration" data-company="Acme">
        Need AI integration
      </a>
    </html>
    """
    source = FreeJobSource(
        "Example Source",
        "https://example.com/",
    )

    source._fetch = lambda: html.decode("utf-8")
    records = source.collect()

    assert len(records) == 1
    assert records[0]["company"] == "Acme"
    assert records[0]["signal"] == "Need AI integration"
    assert records[0]["url"] == "https://example.com/services/ai-integration"


def test_collected_commercial_evidence_preserves_exact_trigger_and_compound_context():
    html = b"""
    <html>
      <a href="/growth" data-company="Acme">
        We raised Series A and are looking for a development partner for AI integration.
      </a>
    </html>
    """
    source = FreeJobSource(
        "Example Source",
        "https://example.com/",
    )
    source._fetch = lambda: html.decode("utf-8")

    records = source.collect()

    assert len(records) == 1
    evidence = records[0]["evidence"].lower()
    assert "raised series a" in evidence
    assert "looking for a development partner" in evidence
    assert "ai integration" in evidence
    assert records[0]["signal_type"] == "commercial_intent"
    assert records[0]["signal_strength"] == "compound"
