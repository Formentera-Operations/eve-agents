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


def load_evidence_rows(manifest: Path) -> list[dict[str, str]]:
    """Rows from an evidence-store nomination manifest (pilot step 2 output:
    key, doc_id, well, category, format_gate, page_count)."""
    with manifest.open(newline="") as f:
        return list(csv.DictReader(f))


def serialize_evidence_pages(key: str, pages: list[dict[str, Any]]) -> str:
    """Render evidence-store page rows as ingest text — the same
    `<!-- source | page -->` shape serialize_view emits, so cognify and
    node-set provenance are indistinguishable across the two sources.
    Pages without text (image-only) are skipped; all-empty docs yield ''."""
    parts = []
    for page in sorted(pages, key=lambda p: p["page_num"]):
        text = (page.get("text") or "").strip()
        if not text:
            continue
        parts.append(f"<!-- source: {key} | page: {page['page_num']} -->\n{text}")
    return "\n\n".join(parts)


def fetch_evidence_pages(doc_id: str) -> list[dict[str, Any]]:
    """Page text for one document straight from the evidence store (MVCC
    reads are safe alongside the service; graph ingest still requires the
    service stopped for the Kuzu write lock, not for this read)."""
    import lancedb

    from ..evidence.config import LANCE_ROOT

    table = lancedb.connect(str(LANCE_ROOT)).open_table("pages")
    safe = doc_id.replace("'", "''")
    return (
        table.search()
        .where(f"doc_id = '{safe}'")
        .select(["page_num", "text"])
        .limit(10_000)
        .to_list()
    )


def sample_trial(
    rows: list[dict[str, str]],
    n: int,
    bucket_cols: tuple[str, str] = ("asset_team", "parse_source"),
) -> list[dict[str, str]]:
    """Deterministic stratified trial slice: spread across asset teams and
    parse tiers (or, for evidence manifests, wells and categories),
    alternating small/large by key length as a size proxy."""
    buckets: dict[tuple[str, str], list[dict[str, str]]] = {}
    for r in rows:
        buckets.setdefault((r[bucket_cols[0]], r[bucket_cols[1]]), []).append(r)
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


def _local_store_present() -> bool:
    """True when the embedded graph store exists locally with real content.

    Resume state lives in SHARED S3 ledgers, but graph data lives in the
    LOCAL gitignored .cognee directory — on a fresh checkout the ledgers
    say "done" while the store is empty, which would silently produce an
    empty graph. Resume is honored only when the local store backs it up.
    """
    from .config import SYSTEM_ROOT

    databases = SYSTEM_ROOT / "databases"
    if not databases.exists():
        return False
    return any(p.stat().st_size > 0 for p in databases.rglob("*") if p.is_file())


def already_ingested_keys() -> set[str]:
    """Keys marked ok in prior ledgers (resume support for add()) — only
    trusted when the local embedded store actually holds prior data."""
    if not _local_store_present():
        return set()
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


async def run(limit: int | None, skip_cognify: bool = False, from_evidence: Path | None = None) -> dict[str, Any]:
    cognee = runtime.get_cognee()
    if from_evidence is not None:
        rows = load_evidence_rows(from_evidence)
        if limit:
            rows = sample_trial(rows, limit, bucket_cols=("well", "category"))
    else:
        rows = load_ingestable_rows()
        if limit:
            rows = sample_trial(rows, limit)
    done = already_ingested_keys()

    ledger: list[dict[str, Any]] = []
    for r in load_no_output_rows() if not (limit or from_evidence) else []:
        ledger.append({"key": r["key"], "status": "no-parse-output", "kind": "", "chars": 0, "seconds": 0, "error": ""})

    total_chars = 0
    for row in rows:
        key = row["key"]
        if key in done:
            ledger.append({"key": key, "status": "skipped-prior-ok", "kind": "", "chars": 0, "seconds": 0, "error": ""})
            continue
        started = time.monotonic()
        try:
            if from_evidence is not None:
                text = serialize_evidence_pages(key, fetch_evidence_pages(row["doc_id"]))
                kind = "evidence-pages"
            else:
                view = fetch_document(key)
                if view is None or (not view["pages"] and not view.get("extraction")):
                    ledger.append({"key": key, "status": "no-parse-output", "kind": "", "chars": 0, "seconds": 0, "error": ""})
                    continue
                text = serialize_view(key, view)
                kind = view["kind"]
            if not text:
                ledger.append({"key": key, "status": "no-parse-output", "kind": kind, "chars": 0, "seconds": 0, "error": ""})
                continue
            await cognee.add(text, dataset_name=DATASET_NAME, node_set=[f"s3key:{key}"])
            total_chars += len(text)
            ledger.append({"key": key, "status": "ok", "kind": kind, "chars": len(text),
                           "seconds": round(time.monotonic() - started, 1), "error": ""})
        except Exception as err:  # per-document failure accounting (R3)
            ledger.append({"key": key, "status": "failed", "kind": "", "chars": 0,
                           "seconds": round(time.monotonic() - started, 1), "error": str(err)[:200]})

    cognify_seconds = 0.0
    if not skip_cognify:
        from cognee.modules.ontology.rdf_xml.RDFLibOntologyResolver import RDFLibOntologyResolver

        # parents[6] = repo root: this module sits one level deeper (graph/)
        # than corpus.py/agent.py, whose parents[5] idiom does NOT transfer.
        ontology = Path(__file__).resolve().parents[6] / "references" / "ontology" / "welldrive.owl"
        if not ontology.exists():
            # RDFLibOntologyResolver silently proceeds without a missing file
            # (verified live) — which would rebuild the graph untyped. Fail loud.
            raise FileNotFoundError(f"ontology not found at {ontology}")
        started = time.monotonic()
        kwargs = {
            "datasets": DATASET_NAME,
            # cognify's parameter is `config`; a mistyped kwarg falls into
            # **kwargs and leaks the resolver object into LLM payloads.
            "config": {"ontology_config": {"ontology_resolver": RDFLibOntologyResolver(ontology_file=str(ontology))}},
        }
        try:
            await cognee.cognify(**kwargs)
        except Exception as err:
            # 1.2.2's first-call migration for the global DB can fail
            # transiently and self-heals on retry (observed live; the error
            # text itself says "it retries automatically on the next call").
            if "migration" not in str(err).lower():
                raise
            await cognee.cognify(**kwargs)
        cognify_seconds = round(time.monotonic() - started, 1)

    report = write_ledger(ledger, total_chars, cognify_seconds)

    if not skip_cognify:
        # R8: exports refresh per ingest run — no second manual command.
        from . import export as graph_export

        report["export"] = await graph_export.run()
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
    parser.add_argument(
        "--from-evidence", type=Path, default=None,
        help="ingest from an evidence-store nomination manifest (key,doc_id,... CSV) instead of the sample manifest",
    )
    args = parser.parse_args()
    print("REMINDER: the analysts service must be stopped during ingest (Kuzu single-writer).")
    asyncio.run(run(args.limit, skip_cognify=args.skip_cognify, from_evidence=args.from_evidence))


if __name__ == "__main__":
    main()
