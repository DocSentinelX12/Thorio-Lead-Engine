from lead_engine.source_adapters import create_adapter
from lead_engine.source_definition import SourceDefinition


def _definition(name: str, url: str) -> SourceDefinition:
    return SourceDefinition(
        name=name,
        provider=name,
        collector_type="html",
        url=url,
        pagination_type="none",
        max_pages=1,
        max_requests=1,
        max_records=10,
    )


def test_source_specific_html_adapter_uses_definition_url(monkeypatch):
    import lead_engine.source_specific_collectors as collectors

    requested = []

    def fake_fetch(request, timeout):
        requested.append(request.full_url)
        return b"<html><body>No job links</body></html>"

    monkeypatch.setattr(collectors, "fetch_url", fake_fetch)

    definition = _definition(
        "NoDesk",
        "https://nodesk.co/remote-jobs/",
    )
    adapter = create_adapter(definition=definition, timeout=12)

    adapter.collect()

    assert requested == ["https://nodesk.co/remote-jobs/"]


def test_renamed_html_detail_sources_keep_their_specialized_adapter(monkeypatch):
    import lead_engine.source_specific_collectors as collectors

    requested = []

    def fake_fetch(request, timeout):
        requested.append(request.full_url)
        return b"<html><body></body></html>"

    monkeypatch.setattr(collectors, "fetch_url", fake_fetch)

    definitions = (
        _definition(
            "USA Remote Work",
            "https://www.usaremotework.com/jobs",
        ),
        _definition(
            "Remote Landers",
            "https://remotelanders.com/jobs",
        ),
    )

    for definition in definitions:
        adapter = create_adapter(definition=definition, timeout=12)
        adapter.collect()

    assert requested == [
        "https://www.usaremotework.com/jobs",
        "https://remotelanders.com/jobs",
    ]
