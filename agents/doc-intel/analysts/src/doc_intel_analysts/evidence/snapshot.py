"""Snapshot publish/restore for the evidence store (U8, KTD8, R12).

Snapshots are Lance-native copies of the whole store directory (blobs
included) to a versioned prefix in the derived bucket:

    s3://formentera-welldrive-derived/runs/doc-intel/evidence/<stamp>/

Restore = download the prefix and point the service at it. Cadence is
after each gated ingest phase, not continuous; the store remains fully
rebuildable from raw corpus + manifest, so snapshots are convenience,
not the durability story.

Run from the analysts directory:

    uv run python -m doc_intel_analysts.evidence.snapshot publish
    uv run python -m doc_intel_analysts.evidence.snapshot restore --stamp 2026-07-06T22-00-00 --dest /tmp/restore
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

DERIVED_BUCKET = "formentera-welldrive-derived"
SNAPSHOT_PREFIX = "runs/doc-intel/evidence"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")


def store_files(lance_root: Path) -> list[Path]:
    """Every file in the Lance dataset, relative paths preserved on publish."""
    return sorted(p for p in lance_root.rglob("*") if p.is_file())


def publish(lance_root: Path, *, stamp: str | None = None, client=None) -> dict:
    """Copy the store to the derived bucket under a versioned stamp."""
    import boto3

    client = client or boto3.client("s3")
    stamp = stamp or _stamp()
    files = store_files(lance_root)
    if not files:
        raise RuntimeError(f"nothing to snapshot at {lance_root}")
    total = 0
    for path in files:
        rel = path.relative_to(lance_root)
        client.upload_file(
            str(path), DERIVED_BUCKET, f"{SNAPSHOT_PREFIX}/{stamp}/{rel}"
        )
        total += path.stat().st_size
    manifest = {
        "stamp": stamp,
        "files": len(files),
        "bytes": total,
        "prefix": f"s3://{DERIVED_BUCKET}/{SNAPSHOT_PREFIX}/{stamp}/",
    }
    client.put_object(
        Bucket=DERIVED_BUCKET,
        Key=f"{SNAPSHOT_PREFIX}/{stamp}/_snapshot.json",
        Body=json.dumps(manifest).encode(),
    )
    return manifest


def restore(stamp: str, dest: Path, *, client=None) -> dict:
    """Download a snapshot into `dest` (becomes a usable lance_root)."""
    import boto3

    client = client or boto3.client("s3")
    prefix = f"{SNAPSHOT_PREFIX}/{stamp}/"
    count = 0
    for page in client.get_paginator("list_objects_v2").paginate(
        Bucket=DERIVED_BUCKET, Prefix=prefix
    ):
        for obj in page.get("Contents", []):
            rel = obj["Key"][len(prefix):]
            if not rel or rel == "_snapshot.json":
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            client.download_file(DERIVED_BUCKET, obj["Key"], str(target))
            count += 1
    if count == 0:
        raise RuntimeError(f"no snapshot found at {prefix}")
    return {"stamp": stamp, "files": count, "dest": str(dest)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evidence store snapshots")
    sub = parser.add_subparsers(dest="command", required=True)
    pub = sub.add_parser("publish")
    pub.add_argument("--stamp", default=None)
    res = sub.add_parser("restore")
    res.add_argument("--stamp", required=True)
    res.add_argument("--dest", type=Path, required=True)
    args = parser.parse_args()

    from doc_intel_analysts.evidence.config import LANCE_ROOT

    if args.command == "publish":
        print(json.dumps(publish(LANCE_ROOT, stamp=args.stamp), indent=2))
    else:
        print(json.dumps(restore(args.stamp, args.dest), indent=2))


if __name__ == "__main__":
    main()
