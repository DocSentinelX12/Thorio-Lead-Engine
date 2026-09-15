from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from typing import Any, Dict

from lead_engine.source_adapters import AdapterResult, create_adapter, normalize_job_record
from lead_engine.source_registry import _load_free_source_catalog


MAX_WORKERS = max(1, min(int(os.environ.get("THORIO_SOURCE_DIAGNOSTIC_WORKERS", "16")), 32))
TIMEOUT = max(1, int(os.environ.get("THORIO_FREE_SOURCE_TIMEOUT", "12")))
MAX_SAMPLES = 3


def _collect_records(source, definition) -> tuple[list[Dict[str, Any]], int]:
    """Collect one bounded page and return production-normalized records."""
    collected = source.collect()
    if isinstance(collected, AdapterResult):
        return list(collected.records), len(collected.records)

    raw = list(collected)
    normalized = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        lead = normalize_job_record(
            item,
            source=definition.name,
            source_url=definition.url,
            definition=definition,
        )
        if lead is not None:
            normalized.append(lead)
    return normalized, len(raw)


def probe(definition) -> Dict[str, Any]:
    # One real request/page per source. This is intentionally non-destructive:
    # no LeadDB, Airtable, queue, qualification, or outreach writes occur here.
    bounded = replace(
        definition,
        max_pages=1,
        max_requests=1,
        max_records=min(int(definition.max_records), 100),
    )
    source = create_adapter(definition=bounded, timeout=TIMEOUT)
    try:
        normalized, raw_count = _collect_records(source, bounded)

        if normalized:
            status = "LIVE_NONZERO"
        elif raw_count:
            status = "LIVE_RAW_BUT_NOT_NORMALIZABLE"
        else:
            status = "LIVE_EMPTY"

        samples = [
            {
                "title": str(item.get("job_title") or item.get("title") or "")[:200],
                "company": str(item.get("company", ""))[:200],
                "url": str(item.get("url", ""))[:500],
            }
            for item in normalized[:MAX_SAMPLES]
        ]
        return {
            "source": definition.name,
            "provider": definition.provider,
            "endpoint": definition.url,
            "collector_type": definition.collector_type,
            "status": status,
            "raw_records": raw_count,
            "normalized_records": len(normalized),
            "samples": samples,
        }
    except Exception as exc:
        return {
            "source": definition.name,
            "provider": definition.provider,
            "endpoint": definition.url,
            "collector_type": definition.collector_type,
            "status": "ERROR",
            "raw_records": 0,
            "normalized_records": 0,
            "error_type": type(exc).__name__,
            "error": str(exc)[:1000],
            "samples": [],
        }


def main() -> int:
    os.environ.setdefault("LEAD_ENGINE_FREE_SOURCES_ENABLED", "1")
    catalog = _load_free_source_catalog()
    definitions = [item for item in catalog if item.enabled and item.allowed_for_thorio]

    results = []
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, max(1, len(definitions))), thread_name_prefix="source-probe") as executor:
        futures = {executor.submit(probe, definition): definition.name for definition in definitions}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)

    results.sort(key=lambda item: item["source"].casefold())
    counts: Dict[str, int] = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1

    report = {
        "catalog_source_count": len(definitions),
        "probe_workers": MAX_WORKERS,
        "per_source_timeout_seconds": TIMEOUT,
        "request_scope": "one real bounded collection request per enabled free source; no persistence or downstream writes",
        "status_counts": counts,
        "results": results,
    }
    with open("source-live-diagnostic.json", "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)

    print("SOURCE LIVE DIAGNOSTIC SUMMARY", flush=True)
    print(json.dumps({"catalog_source_count": len(definitions), "status_counts": counts}, sort_keys=True), flush=True)

    # A live empty source is not automatically a failure. It is evidence that
    # the endpoint responded successfully but yielded no current records.
    # Hard failure is reserved for transport/collector errors or records that
    # cannot be normalized despite the endpoint returning data.
    hard_failures = [
        item for item in results
        if item["status"] in {"ERROR", "LIVE_RAW_BUT_NOT_NORMALIZABLE"}
    ]
    if hard_failures:
        print("SOURCE LIVE DIAGNOSTIC: hard failures detected.", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
