"""Ledger-driven evidence ingest CLI (U3; Westlake listing mode for U7).

Run from the analysts directory:

    uv run python -m doc_intel_analysts.evidence.ingest --manifest ../../../corpus/sample-manifest.csv
    uv run python -m doc_intel_analysts.evidence.ingest --prefix "WESTLAKE RESOURCES/"
    uv run python -m doc_intel_analysts.evidence.ingest --manifest ... --limit 25 --dry-run

Resumable and idempotent per document (KTD6): the ledger short-circuits
unchanged docs by checksum; interrupted or failed docs re-run. Emits a JSON
report to stdout, mirroring `graph/ingest.py`.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from doc_intel_analysts.evidence import parse
from doc_intel_analysts.evidence.config import RAW_BUCKET, load_config
from doc_intel_analysts.evidence.store import EvidenceStore, checksum_bytes


def manifest_entries(manifest_path: Path) -> list[dict]:
    """Unique (key, asset_team) pairs from the sample manifest."""
    seen: set[str] = set()
    entries = []
    with open(manifest_path) as handle:
        for row in csv.DictReader(handle):
            key = row["key"]
            if key in seen:
                continue
            seen.add(key)
            entries.append({"key": key, "asset_team": row.get("asset_team", "")})
    return entries


def prefix_entries(prefix: str) -> list[dict]:
    """List raw-bucket objects under a prefix (Westlake mode, U7).

    The asset team is the first path segment, matching the archive layout
    `{asset_team}/{well}/{category}/...`.
    """
    import boto3

    client = boto3.client("s3")
    entries = []
    for page in client.get_paginator("list_objects_v2").paginate(
        Bucket=RAW_BUCKET, Prefix=prefix
    ):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue
            entries.append(
                {
                    "key": key,
                    "asset_team": key.split("/", 1)[0],
                    # ETag lets re-runs short-circuit completed docs from the
                    # listing alone — no per-object fetch. Essential at
                    # Westlake scale (37k objects, multi-day resumable runs).
                    "etag": obj.get("ETag", "").strip('"'),
                }
            )
    return entries


def run_ingest(
    entries: list[dict],
    store: EvidenceStore,
    parsed_root: Path,
    *,
    limit: int | None = None,
    fetch=parse.fetch_raw_bytes,
    progress_every: int = 25,
    max_new: int | None = None,
) -> dict:
    if limit is not None:
        entries = entries[:limit]
    ledger = store.ledger_snapshot()
    reconciled = store.reconcile_orphans(ledger)
    if reconciled:
        print(
            f"reconciled {reconciled} orphaned doc(s) from an interrupted run",
            file=sys.stderr,
        )
    report = {
        "requested": len(entries),
        "complete": 0,
        "unchanged": 0,
        "skipped": 0,
        "failed": 0,
        "failures": [],
        "reconciled": reconciled,
        "stopped_early": False,
    }
    for index, entry in enumerate(entries, 1):
        # Batch mode (memory bound): stop before starting another doc once N
        # units of real work (complete/skipped/failed — anything that wrote
        # the ledger) are done, so the driver can relaunch a fresh process —
        # the only reliable way to return parser/OCR memory to the OS.
        # Checked at the top of the loop so consecutive runs of skips or
        # failures can't overshoot the cap.
        new_work = report["complete"] + report["skipped"] + report["failed"]
        if max_new is not None and new_work >= max_new:
            report["stopped_early"] = True
            break
        key = entry["key"]
        doc_id = parse.doc_id_for_key(key)
        etag = entry.get("etag", "")
        if etag and not store.needs_ingest(doc_id, f"etag:{etag}", ledger=ledger):
            report["unchanged"] += 1
            continue
        # Format-gate skips need no bytes: classify on the key alone, so
        # 5k Excel-family files aren't re-fetched on every pass.
        gate = parse.classify(key)
        if gate.startswith("skip:"):
            skip = parse.SkipRecord(s3key=key, doc_id=doc_id, reason=gate[5:])
            store.record_skip(skip, f"etag:{etag}" if etag else "")
            report["skipped"] += 1
            continue
        try:
            data = fetch(key)
        except Exception as exc:  # noqa: BLE001 — fetch failures reach the ledger
            skip = parse.SkipRecord(
                s3key=key,
                doc_id=parse.doc_id_for_key(key),
                reason=f"fetch failed: {exc}",
            )
            store.record_skip(skip, status="failed")
            report["failed"] += 1
            report["failures"].append({"key": key, "reason": skip.reason})
            continue

        checksum = f"etag:{etag}" if etag else checksum_bytes(data)
        if not store.needs_ingest(doc_id, checksum, ledger=ledger):
            report["unchanged"] += 1
            continue

        result = parse.parse_document(
            key, data, parsed_root, asset_team=entry["asset_team"]
        )
        if isinstance(result, parse.SkipRecord):
            if result.retriable:
                # Parse exceptions may be environmental (parser bug, memory
                # pressure), not a property of the bytes — record without a
                # checksum so the next pass retries, and count as failed.
                store.record_skip(result, status="failed")
                report["failed"] += 1
                report["failures"].append({"key": key, "reason": result.reason})
            else:
                store.record_skip(result, checksum)
                report["skipped"] += 1
            continue

        outcome = store.upsert_document(result, checksum)
        report[outcome.status if outcome.status in report else "failed"] += 1
        if outcome.status == "failed":
            report["failures"].append({"key": key, "reason": outcome.reason})
        if index % progress_every == 0:
            print(
                f"[{index}/{len(entries)}] complete={report['complete']} "
                f"skipped={report['skipped']} failed={report['failed']}",
                file=sys.stderr,
            )

    # Batch mode always defers maintenance to its own invocation — even the
    # batch that finishes the listing must not stack the FTS rebuild on a
    # parse process (the driver runs a final full --maintain instead).
    if report["stopped_early"] or max_new is not None:
        return report

    store.build_indexes()
    store.optimize()
    report["table_counts"] = store.counts()
    report["store_bytes"] = sum(
        f.stat().st_size
        for f in store._config.lance_root.rglob("*")
        if f.is_file()
    )
    return report


def main() -> None:
    parser_ = argparse.ArgumentParser(description="Evidence store ingest")
    source = parser_.add_mutually_exclusive_group()
    source.add_argument("--manifest", type=Path, help="sample manifest CSV")
    source.add_argument("--prefix", help="raw-bucket prefix (Westlake mode)")
    parser_.add_argument("--limit", type=int, default=None)
    parser_.add_argument(
        "--max-new",
        type=int,
        default=None,
        help="batch mode: exit after N docs of real work (skips index build "
        "and compaction — run --maintain between batches)",
    )
    parser_.add_argument(
        "--maintain",
        action="store_true",
        help="run index build + compaction only, then exit (no source needed)",
    )
    parser_.add_argument(
        "--light",
        action="store_true",
        help="with --maintain: compact only the churn-heavy small tables "
        "(documents, ledger) — no FTS rebuild, no pages/chunks compaction",
    )
    parser_.add_argument(
        "--dry-run", action="store_true", help="list what would be ingested, no writes"
    )
    args = parser_.parse_args()

    if args.light and not args.maintain:
        parser_.error("--light requires --maintain")
    if args.maintain:
        config = load_config()
        store = EvidenceStore(config)
        if args.light:
            store.optimize(["documents", "ledger"])
        else:
            store.build_indexes()
            store.optimize()
        print(
            json.dumps(
                {"maintain": True, "light": args.light, "table_counts": store.counts()},
                indent=2,
            )
        )
        return
    if not (args.manifest or args.prefix):
        parser_.error("one of --manifest / --prefix is required (or --maintain)")

    entries = (
        manifest_entries(args.manifest) if args.manifest else prefix_entries(args.prefix)
    )
    if args.dry_run:
        gates: dict[str, int] = {}
        for entry in entries[: args.limit]:
            gate = parse.classify(entry["key"])
            gate = gate if not gate.startswith("skip:") else "skip"
            gates[gate] = gates.get(gate, 0) + 1
        print(json.dumps({"entries": len(entries), "format_gates": gates}, indent=2))
        return

    config = load_config()
    store = EvidenceStore(config)
    report = run_ingest(
        entries, store, config.parsed_root, limit=args.limit, max_new=args.max_new
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
