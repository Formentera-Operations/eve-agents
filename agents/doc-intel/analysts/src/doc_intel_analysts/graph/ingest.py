"""Ingest parsed corpus documents into the knowledge graph (plan U3).

One cognee.add() per document — node_set tag carries the S3 key (KTD3) and
per-document exceptions land in the ledger (R3). cognify runs once at the end
with the ontology; 1.2.2 qualifies pipeline runs per data item, so re-running
after a partial failure skips already-processed items (verified at unit start
against installed source: modules/pipelines/layers/check_pipeline_run_qualification.py).

Operational rule (Risks): the analysts service must be STOPPED during ingest —
embedded Kuzu is single-writer and an idle service still holds the lock.

Usage:
    uv run python -m doc_intel_analysts.graph.ingest --limit 20   # trial slice
    uv run python -m doc_intel_analysts.graph.ingest              # full run
"""

import argparse
import asyncio
import csv
import io
import json
import time
from pathlib import Path
from typing import Any

from ..corpus import _MANIFEST_PATH, DERIVED_BUCKET, _s3, fetch_document
from . import runtime
from .config import DATASET_NAME

LEDGER_PREFIX = "runs/doc-intel/graph/ledgers/"


def load_ingestable_rows() -> list[dict[str, str]]:
    """Manifest rows that carry parse output (311 expected; R4)."""
    with _MANIFEST_PATH.open(newline="") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r["parsed_ref"]]


def load_no_output_rows() -> list[dict[str, str]]:
    """Pilot rows with no usable parse output — ledgered, never 'failed'."""
    with _MANIFEST_PATH.open(newline="") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if not r["parsed_ref"] and r["parse_source"].startswith("pilot-")]


def serialize_view(key: str, view: dict[str, Any]) -> str:
    """Render a parsed view as ingest text, branching on kind (review fix:
    tier-A extractions live in fields, not pages, and must not ingest empty)."""
    if view["kind"] == "extraction":
        ex = view.get("extraction") or {}
        body = json.dumps(
            {"fields": ex.get("fields", {}), "field_page_citations": ex.get("field_pages", {})},
            indent=1,
        )
        return f"<!-- source: {key} | structured extraction -->\n{body}"
    parts = []
    for page in view["pages"]:
        parts.append(f"<!-- source: {key} | page: {page['page']} -->\n{page['markdown']}")
    return "\n\n".join(parts)


def sample_trial(rows: list[dict[str, str]], n: int) -> list[dict[str, str]]:
    """Deterministic stratified trial slice: spread across asset teams and
    parse tiers, alternating small/large by key length as a size proxy."""
    buckets: dict[tuple[str, str], list[dict[str, str]]] = {}
    for r in rows:
        buckets.setdefault((r["asset_team"], r["parse_source"]), []).append(r)
    for b in buckets.values():
        b.sort(key=lambda r: r["key"])
    picked: list[dict[str, str]] = []
    keys = sorted(buckets)
    i = 0
    while len(picked) < n and any(buckets[k] for k in keys):
        k = keys[i % len(keys)]
        if buckets[k]:
            # alternate ends of the sorted bucket to mix document shapes
            picked.append(buckets[k].pop(0 if len(picked) % 2 == 0 else -1))
        i += 1
    return picked[:n]


def already_ingested_keys() -> set[str]:
    """Keys marked ok in prior ledgers (resume support for add())."""
    done: set[str] = set()
    try:
        resp = _s3.list_objects_v2(Bucket=DERIVED_BUCKET, Prefix=LEDGER_PREFIX)
        for obj in resp.get("Contents", []):
            body = _s3.get_object(Bucket=DERIVED_BUCKET, Key=obj["Key"])["Body"].read()
            for row in csv.DictReader(io.StringIO(body.decode())):
                if row.get("status") == "ok":
                    done.add(row["key"])
    except Exception:
        pass
    return done


async def run(limit: int | None, skip_cognify: bool = False) -> dict[str, Any]:
    cognee = runtime.get_cognee()
    rows = load_ingestable_rows()
    if limit:
        rows = sample_trial(rows, limit)
    done = already_ingested_keys()

    ledger: list[dict[str, Any]] = []
    for r in load_no_output_rows() if not limit else []:
        ledger.append({"key": r["key"], "status": "no-parse-output", "kind": "", "chars": 0, "seconds": 0, "error": ""})

    total_chars = 0
    for row in rows:
        key = row["key"]
        if key in done:
            ledger.append({"key": key, "status": "skipped-prior-ok", "kind": "", "chars": 0, "seconds": 0, "error": ""})
            continue
        started = time.monotonic()
        try:
            view = fetch_document(key)
            if view is None or (not view["pages"] and not view.get("extraction")):
                ledger.append({"key": key, "status": "no-parse-output", "kind": "", "chars": 0, "seconds": 0, "error": ""})
                continue
            text = serialize_view(key, view)
            await cognee.add(text, dataset_name=DATASET_NAME, node_set=[f"s3key:{key}"])
            total_chars += len(text)
            ledger.append({"key": key, "status": "ok", "kind": view["kind"], "chars": len(text),
                           "seconds": round(time.monotonic() - started, 1), "error": ""})
        except Exception as err:  # per-document failure accounting (R3)
            ledger.append({"key": key, "status": "failed", "kind": "", "chars": 0,
                           "seconds": round(time.monotonic() - started, 1), "error": str(err)[:200]})

    cognify_seconds = 0.0
    if not skip_cognify:
        from cognee.modules.ontology.rdf_xml.RDFLibOntologyResolver import RDFLibOntologyResolver

        ontology = Path(__file__).resolve().parents[5] / "references" / "ontology" / "welldrive.owl"
        started = time.monotonic()
        await cognee.cognify(
            datasets=DATASET_NAME,
            ontology_config={"ontology_resolver": RDFLibOntologyResolver(ontology_file=str(ontology))},
        )
        cognify_seconds = round(time.monotonic() - started, 1)

    report = write_ledger(ledger, total_chars, cognify_seconds)
    return report


def write_ledger(ledger: list[dict[str, Any]], total_chars: int, cognify_seconds: float) -> dict[str, Any]:
    stamp = time.strftime("%Y-%m-%d-%H%M%S")
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["key", "status", "kind", "chars", "seconds", "error"])
    writer.writeheader()
    writer.writerows(ledger)
    ledger_key = f"{LEDGER_PREFIX}{stamp}.csv"
    _s3.put_object(Bucket=DERIVED_BUCKET, Key=ledger_key, Body=buf.getvalue().encode(), ContentType="text/csv")

    counts: dict[str, int] = {}
    for row in ledger:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    report = {
        "ledger": f"s3://{DERIVED_BUCKET}/{ledger_key}",
        "counts": counts,
        "total_chars_added": total_chars,
        "cognify_seconds": cognify_seconds,
        "note": (
            "Cost: check the AI Gateway usage dashboard delta for this run window "
            "(cognify LLM+embedding calls route through it exclusively). cognify is "
            "per-item qualified in 1.2.2 — re-runs skip processed items. Per-doc rate "
            "may scale superlinearly with graph size; judge a range, not a flat multiple."
        ),
    }
    print(json.dumps(report, indent=1))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="trial-slice size (stratified sample)")
    parser.add_argument("--skip-cognify", action="store_true", help="add() only, no graph build")
    args = parser.parse_args()
    print("REMINDER: the analysts service must be stopped during ingest (Kuzu single-writer).")
    asyncio.run(run(args.limit, skip_cognify=args.skip_cognify))


if __name__ == "__main__":
    main()
