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


def test_jobicy_probe_uses_current_json_api_definition():
    from lead_engine.source_registry import _load_free_source_catalog

    definitions, _ = _probe_definitions(_load_free_source_catalog())
    jobicy = next(item for item in definitions if item.name == "Jobicy")

    assert jobicy.collector_type == "json"
    assert jobicy.url == "https://jobicy.com/api/v2/remote-jobs?count=200"
    assert jobicy.record_path == "jobs"
    assert jobicy.title_field == "jobTitle"
    assert jobicy.company_field == "companyName"
    assert jobicy.description_field == "jobDescription"
    assert jobicy.url_field == "url"
    assert jobicy.source_id_field == "id"
    assert jobicy.location_field == "jobGeo"
