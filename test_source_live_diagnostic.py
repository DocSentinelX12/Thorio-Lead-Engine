from lead_engine.source_definition import SourceDefinition
from scripts.source_live_diagnostic import _probe_definitions


def test_probe_includes_enabled_sources_even_when_thorio_route_flag_is_false():
    allowed = SourceDefinition(
        name="Allowed Source",
        provider="test",
        collector_type="json",
        url="https://example.com/allowed",
        enabled=True,
        allowed_for_thorio=True,
    )
    research_only_flag = SourceDefinition(
        name="Research Source",
        provider="test",
        collector_type="json",
        url="https://example.com/research",
        enabled=True,
        allowed_for_thorio=False,
    )
    disabled = SourceDefinition(
        name="Disabled Source",
        provider="test",
        collector_type="json",
        url="https://example.com/disabled",
        enabled=False,
        allowed_for_thorio=False,
    )

    definitions, excluded = _probe_definitions(
        (allowed, research_only_flag, disabled)
    )

    assert {item.name for item in definitions} == {
        "Allowed Source",
        "Research Source",
    }
    assert excluded == ["Disabled Source"]
