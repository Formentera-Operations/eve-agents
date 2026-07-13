"""Bootstrap down-sync of the evidence replica from S3 (U5; R4, R9, KTD3).

Stands up a complete replica of the doc-intel stores on a fresh volume (the
Azure Files NFS mount) by down-syncing four prefixes from the derived bucket,
then verifying per-key parity (relative path + size) per prefix — a stricter
form of the count/byte check the Phase 1 laptop sync did
(`.evidence/s3-sync-phase1.sh`).

S3 layout, all under ``s3://formentera-welldrive-derived/``:

    runs/doc-intel/evidence/lance/    -> <dest>/.evidence/lance/   (Phase 1)
    runs/doc-intel/evidence/parsed/   -> <dest>/.evidence/parsed/  (Phase 1)
    runs/doc-intel/evidence/cognee/   -> <dest>/.cognee/
    runs/doc-intel/evidence/masters/  -> <dest>/.masters/

The ``cognee/`` and ``masters/`` prefixes are chosen here as clean siblings
of the Phase 1 pair; the laptop-side upload (the Phase 1 script extension)
must push to these exact prefixes. Versioned snapshot stamps published by
``snapshot.py`` live as sibling prefixes (``runs/doc-intel/evidence/<stamp>/``)
and are never touched by the bootstrap.

Idempotent resume: an object is skipped when the local file exists with
matching size AND a matching ETag; multipart ETags (containing ``-``) cannot
be recomputed locally, so size parity suffices for those. A re-run after a
mid-transfer failure therefore picks up where it left off. A killed run can
also strand boto3 s3transfer temp files (random-suffix siblings of their
targets); verification reports these as extras and ``--remove-extras``
deletes them.

Run from the analysts directory (or the one-off gate Job container):

    python -m doc_intel_analysts.evidence.replica --bootstrap [--dest PATH] \
        [--dry-run] [--remove-extras]

Exit status is nonzero when any prefix fails post-sync per-key parity
(missing, size-mismatched, or extra local files).
"""

import argparse
import hashlib
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DERIVED_BUCKET = "formentera-welldrive-derived"
EVIDENCE_PREFIX = "runs/doc-intel/evidence"

# Same resolution as config.py: evidence/replica.py -> the analysts dir that
# houses .evidence/.cognee/.masters (the mount root in the gate job).
_PACKAGE_ROOT = Path(__file__).resolve().parents[3]

_PROGRESS_EVERY = 200
_MD5_CHUNK = 1 << 20
_EXAMPLE_PATHS = 10


@dataclass(frozen=True)
class SyncTarget:
    name: str
    prefix: str  # S3 key prefix, trailing slash
    local_subdir: str  # relative to --dest


SYNC_TARGETS: tuple[SyncTarget, ...] = (
    SyncTarget("lance", f"{EVIDENCE_PREFIX}/lance/", ".evidence/lance"),
    SyncTarget("parsed", f"{EVIDENCE_PREFIX}/parsed/", ".evidence/parsed"),
    SyncTarget("cognee", f"{EVIDENCE_PREFIX}/cognee/", ".cognee"),
    SyncTarget("masters", f"{EVIDENCE_PREFIX}/masters/", ".masters"),
)


@dataclass(frozen=True)
class RemoteObject:
    key: str
    size: int
    etag: str  # normalized: surrounding quotes stripped


def _make_client() -> Any:
    import boto3

    return boto3.client("s3")


def _list_remote(client: Any, prefix: str) -> list[RemoteObject]:
    objects: list[RemoteObject] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=DERIVED_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith("/"):
                continue  # directory placeholder
            objects.append(
                RemoteObject(obj["Key"], obj["Size"], obj["ETag"].strip('"'))
            )
    return objects


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_MD5_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _up_to_date(local: Path, remote: RemoteObject) -> bool:
    if not local.is_file() or local.stat().st_size != remote.size:
        return False
    if "-" in remote.etag:
        return True  # multipart ETag: size parity is the contract
    return _md5(local) == remote.etag


def _sync_target(
    client: Any, target: SyncTarget, dest: Path, *, dry_run: bool
) -> dict[str, Any]:
    local_root = dest / target.local_subdir
    remote = _list_remote(client, target.prefix)
    to_download: list[RemoteObject] = []
    skipped = 0
    skipped_bytes = 0
    for obj in remote:
        if _up_to_date(local_root / obj.key[len(target.prefix) :], obj):
            skipped += 1
            skipped_bytes += obj.size
        else:
            to_download.append(obj)
    download_bytes = sum(o.size for o in to_download)

    if not dry_run:
        for done, obj in enumerate(to_download, start=1):
            local = local_root / obj.key[len(target.prefix) :]
            local.parent.mkdir(parents=True, exist_ok=True)
            client.download_file(DERIVED_BUCKET, obj.key, str(local))
            if done % _PROGRESS_EVERY == 0:
                logger.info(
                    "%s: %d/%d objects downloaded", target.name, done, len(to_download)
                )
    logger.info(
        "%s: %d to download (%d bytes), %d skipped (%d bytes)%s",
        target.name,
        len(to_download),
        download_bytes,
        skipped,
        skipped_bytes,
        " [dry run]" if dry_run else "",
    )
    return {
        "name": target.name,
        "prefix": target.prefix,
        "download": len(to_download),
        "download_bytes": download_bytes,
        "skip": skipped,
        "skip_bytes": skipped_bytes,
    }


def _local_files(root: Path) -> dict[str, int]:
    if not root.is_dir():
        return {}
    return {
        p.relative_to(root).as_posix(): p.stat().st_size
        for p in root.rglob("*")
        if p.is_file()
    }


def _verify_target(
    client: Any, target: SyncTarget, dest: Path, *, remove_extras: bool = False
) -> dict[str, Any]:
    """Per-key parity (relative path + size), remote listing vs local tree.

    Reports three categories: ``missing`` (listed, absent locally),
    ``size_mismatch`` (present, wrong size), and ``extras`` (local files not
    in the listing, e.g. s3transfer temp files stranded by a killed run).
    With ``remove_extras`` the extras are deleted and the target re-verified.
    """
    local_root = dest / target.local_subdir
    expected = {
        obj.key[len(target.prefix) :]: obj.size
        for obj in _list_remote(client, target.prefix)
    }
    local = _local_files(local_root)
    missing = sorted(rel for rel in expected if rel not in local)
    size_mismatch = sorted(
        rel for rel, size in expected.items() if rel in local and local[rel] != size
    )
    extras = sorted(rel for rel in local if rel not in expected)
    if remove_extras and extras:
        for rel in extras:
            (local_root / rel).unlink()
        logger.info("%s: removed %d extra local file(s)", target.name, len(extras))
        return _verify_target(client, target, dest)
    return {
        "name": target.name,
        "remote_count": len(expected),
        "remote_bytes": sum(expected.values()),
        "local_count": len(local),
        "local_bytes": sum(local.values()),
        "missing": missing,
        "size_mismatch": size_mismatch,
        "extras": extras,
        "ok": not (missing or size_mismatch or extras),
    }


def bootstrap(
    dest: Path,
    *,
    dry_run: bool = False,
    remove_extras: bool = False,
    client: Any = None,
) -> dict[str, Any]:
    """Sync all four prefixes into `dest`, then verify (unless dry-run)."""
    client = client or _make_client()
    report: dict[str, Any] = {
        "dest": str(dest),
        "dry_run": dry_run,
        "targets": [
            _sync_target(client, target, dest, dry_run=dry_run)
            for target in SYNC_TARGETS
        ],
        "ok": True,
    }
    if not dry_run:
        verification = [
            _verify_target(client, target, dest, remove_extras=remove_extras)
            for target in SYNC_TARGETS
        ]
        report["verification"] = verification
        report["ok"] = all(row["ok"] for row in verification)
    return report


def _example_paths(paths: list[str]) -> str:
    shown = ", ".join(paths[:_EXAMPLE_PATHS])
    return shown if len(paths) <= _EXAMPLE_PATHS else f"{shown}, ..."


def _print_summary(report: dict[str, Any]) -> None:
    if report["dry_run"]:
        print(f"dry run — sync plan for {report['dest']} (nothing transferred)")
        print(f"{'prefix':<10} {'download':>9} {'skip':>7} {'bytes to transfer':>18}")
        for row in report["targets"]:
            print(
                f"{row['name']:<10} {row['download']:>9} {row['skip']:>7}"
                f" {row['download_bytes']:>18}"
            )
        return
    print(f"verification — remote vs local under {report['dest']}")
    print(f"{'prefix':<10} {'remote (files/bytes)':>24} {'local (files/bytes)':>24} status")
    for row in report["verification"]:
        status = "OK" if row["ok"] else "MISMATCH"
        remote = f"{row['remote_count']} / {row['remote_bytes']}"
        local = f"{row['local_count']} / {row['local_bytes']}"
        print(f"{row['name']:<10} {remote:>24} {local:>24} {status}")
    for row in report["verification"]:
        if row["missing"]:
            print(
                f"{row['name']}: {len(row['missing'])} missing locally:"
                f" {_example_paths(row['missing'])}"
            )
        if row["size_mismatch"]:
            print(
                f"{row['name']}: {len(row['size_mismatch'])} size mismatch:"
                f" {_example_paths(row['size_mismatch'])}"
            )
        if row["extras"]:
            print(
                f"{row['name']}: {len(row['extras'])} extra local file(s) not in"
                f" the remote listing: {_example_paths(row['extras'])}"
                " (re-run with --remove-extras to delete them)"
            )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap the evidence replica from the derived bucket."
    )
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        required=True,
        help="down-sync lance/parsed/cognee/masters and verify parity",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=_PACKAGE_ROOT,
        help="replica root housing .evidence/.cognee/.masters "
        f"(default: {_PACKAGE_ROOT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the sync plan without transferring anything",
    )
    parser.add_argument(
        "--remove-extras",
        action="store_true",
        help="delete local files absent from the remote listing before verifying",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    report = bootstrap(
        args.dest, dry_run=args.dry_run, remove_extras=args.remove_extras
    )
    _print_summary(report)
    if not report["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
