"""U5 contract tests: bootstrap replica sync (dry-run plan, skip logic, verify,
extras remediation).

Thin by design — stubbed S3 client, temp dirs, no network. The real proof
is the gate run in Azure.
"""

import hashlib
import threading
import time
from pathlib import Path

import pytest

from doc_intel_analysts.evidence import replica

LANCE = f"{replica.EVIDENCE_PREFIX}/lance/"
PARSED = f"{replica.EVIDENCE_PREFIX}/parsed/"
COGNEE = f"{replica.EVIDENCE_PREFIX}/cognee/"
MASTERS = f"{replica.EVIDENCE_PREFIX}/masters/"


class FakeS3:
    """In-memory stand-in for the two client methods replica uses.

    Thread-safe like the real low-level client: `download_file` may be called
    concurrently, so recorded state is guarded by a lock. `download_delay`
    keeps downloads in flight long enough for concurrency to be observable
    (`max_in_flight`); keys in `fail_keys` write a partial file then raise,
    modeling a mid-transfer failure.
    """

    def __init__(
        self,
        objects: dict[str, bytes],
        *,
        multipart: set[str] | None = None,
        listed_size_override: dict[str, int] | None = None,
        download_delay: float = 0.0,
        fail_keys: set[str] | None = None,
    ):
        self.objects = objects
        self.multipart = multipart or set()
        self.listed_size_override = listed_size_override or {}
        self.download_delay = download_delay
        self.fail_keys = fail_keys if fail_keys is not None else set()
        self.downloads: list[str] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self._lock = threading.Lock()

    def _etag(self, key: str) -> str:
        digest = hashlib.md5(self.objects[key]).hexdigest()
        if key in self.multipart:
            return f'"{digest}-3"'
        return f'"{digest}"'

    def get_paginator(self, name: str):
        assert name == "list_objects_v2"
        fake = self

        class Paginator:
            def paginate(self, Bucket: str, Prefix: str):
                assert Bucket == replica.DERIVED_BUCKET
                keys = sorted(k for k in fake.objects if k.startswith(Prefix))
                if not keys:
                    yield {}
                    return
                # Two keys per page so pagination is actually exercised.
                for i in range(0, len(keys), 2):
                    yield {
                        "Contents": [
                            {
                                "Key": k,
                                "Size": fake.listed_size_override.get(
                                    k, len(fake.objects[k])
                                ),
                                "ETag": fake._etag(k),
                            }
                            for k in keys[i : i + 2]
                        ]
                    }

        return Paginator()

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        with self._lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.download_delay:
                time.sleep(self.download_delay)
            if key in self.fail_keys:
                Path(filename).write_bytes(b"partial-write-then-died")
                raise RuntimeError(f"injected download failure: {key}")
            with self._lock:
                self.downloads.append(key)
            Path(filename).write_bytes(self.objects[key])
        finally:
            with self._lock:
                self.in_flight -= 1


def _prewrite(dest: Path, subpath: str, content: bytes) -> Path:
    path = dest / subpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_dry_run_reports_plan_and_transfers_nothing(tmp_path, capsys):
    fake = FakeS3(
        {
            f"{LANCE}pages.lance/data/a.bin": b"lance-data-one",
            f"{LANCE}pages.lance/data/b.bin": b"lance-data-two!",
            f"{PARSED}doc1.json": b'{"pages": 3}',
            f"{COGNEE}kuzu/graph.db": b"graph-bytes",
            f"{MASTERS}nodes.csv": b"id,name\n1,x\n",
        }
    )
    # One lance object already up to date locally (size + etag match).
    _prewrite(tmp_path, ".evidence/lance/pages.lance/data/a.bin", b"lance-data-one")

    report = replica.bootstrap(tmp_path, dry_run=True, client=fake)

    assert fake.downloads == []
    assert report["ok"] is True and "verification" not in report
    by_name = {t["name"]: t for t in report["targets"]}
    assert by_name["lance"]["download"] == 1 and by_name["lance"]["skip"] == 1
    assert by_name["lance"]["download_bytes"] == len(b"lance-data-two!")
    assert by_name["parsed"]["download"] == 1
    assert by_name["cognee"]["download"] == 1
    assert by_name["masters"]["download"] == 1
    # Dry run created nothing beyond the pre-written file.
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert len(files) == 1

    replica._print_summary(report)
    out = capsys.readouterr().out
    assert "dry run" in out
    for name in ("lance", "parsed", "cognee", "masters"):
        assert name in out


@pytest.mark.parametrize("workers", [1, 8])
def test_skip_up_to_date_and_redownload_mismatches(tmp_path, workers):
    fresh = f"{LANCE}tbl/fresh.bin"
    short = f"{LANCE}tbl/short.bin"
    drift = f"{PARSED}drift.json"
    multi = f"{MASTERS}big.csv"
    fake = FakeS3(
        {
            fresh: b"payload-abc",
            short: b"full-remote-content",
            drift: b"remote-json",
            multi: b"payload-abc",
        },
        multipart={multi},
    )
    # Up to date: size + etag match -> untouched.
    _prewrite(tmp_path, ".evidence/lance/tbl/fresh.bin", b"payload-abc")
    # Size mismatch -> re-downloaded.
    _prewrite(tmp_path, ".evidence/lance/tbl/short.bin", b"trunc")
    # Same size, etag mismatch -> re-downloaded.
    _prewrite(tmp_path, ".evidence/parsed/drift.json", b"local-!json")
    # Multipart etag ('-'): size match suffices -> untouched.
    _prewrite(tmp_path, ".masters/big.csv", b"XXXXXXX-abc")

    report = replica.bootstrap(tmp_path, dry_run=False, client=fake, workers=workers)

    assert sorted(fake.downloads) == sorted([short, drift])
    assert (tmp_path / ".evidence/lance/tbl/short.bin").read_bytes() == (
        b"full-remote-content"
    )
    assert (tmp_path / ".evidence/parsed/drift.json").read_bytes() == b"remote-json"
    assert (tmp_path / ".masters/big.csv").read_bytes() == b"XXXXXXX-abc"
    assert report["ok"] is True
    assert all(v["ok"] for v in report["verification"])
    if workers == 1:
        # workers=1 is the plain sequential path: never more than one in flight.
        assert fake.max_in_flight == 1


def test_extra_local_file_fails_verification_with_named_paths(
    tmp_path, monkeypatch, capsys
):
    key = f"{LANCE}tbl/data.bin"
    fake = FakeS3({key: b"payload-abc"})
    _prewrite(tmp_path, ".evidence/lance/tbl/data.bin", b"payload-abc")
    # Orphaned s3transfer temp file: same directory, random suffix, stranded
    # by a killed run. Not in the remote listing -> must fail as an extra.
    _prewrite(tmp_path, ".evidence/lance/tbl/data.bin.6aF3xQ", b"partial")
    monkeypatch.setattr(replica, "_make_client", lambda: fake)

    with pytest.raises(SystemExit) as excinfo:
        replica.main(["--bootstrap", "--dest", str(tmp_path)])

    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "MISMATCH" in out
    assert "tbl/data.bin.6aF3xQ" in out
    assert "--remove-extras" in out


def test_remove_extras_deletes_orphans_and_passes(tmp_path, monkeypatch, capsys):
    key = f"{LANCE}tbl/data.bin"
    fake = FakeS3({key: b"payload-abc"})
    _prewrite(tmp_path, ".evidence/lance/tbl/data.bin", b"payload-abc")
    orphan = _prewrite(tmp_path, ".evidence/lance/tbl/data.bin.6aF3xQ", b"partial")
    monkeypatch.setattr(replica, "_make_client", lambda: fake)

    replica.main(["--bootstrap", "--dest", str(tmp_path), "--remove-extras"])

    assert not orphan.exists()
    assert (tmp_path / ".evidence/lance/tbl/data.bin").read_bytes() == b"payload-abc"
    out = capsys.readouterr().out
    assert "MISMATCH" not in out
    assert "OK" in out


def test_verification_mismatch_exits_nonzero(tmp_path, monkeypatch, capsys):
    key = f"{LANCE}tbl/lied-about.bin"
    # Listing claims 999 bytes; the transferred object is smaller, so the
    # post-sync count/byte parity check must fail.
    fake = FakeS3({key: b"tiny"}, listed_size_override={key: 999})
    monkeypatch.setattr(replica, "_make_client", lambda: fake)

    with pytest.raises(SystemExit) as excinfo:
        replica.main(["--bootstrap", "--dest", str(tmp_path)])

    assert excinfo.value.code == 1
    assert "MISMATCH" in capsys.readouterr().out


def test_concurrent_download_happy_path(tmp_path, monkeypatch, capsys):
    # 50 objects with a per-download delay: with --workers 8 the pool must
    # overlap transfers (bounded by the cap) and still land every byte.
    objects = {
        f"{COGNEE}chunks/{i:04d}.bin": f"content-{i:04d}".encode() for i in range(50)
    }
    fake = FakeS3(objects, download_delay=0.005)
    monkeypatch.setattr(replica, "_make_client", lambda: fake)

    replica.main(["--bootstrap", "--dest", str(tmp_path), "--workers", "8"])

    assert sorted(fake.downloads) == sorted(objects)
    for key, content in objects.items():
        assert (tmp_path / ".cognee" / key[len(COGNEE) :]).read_bytes() == content
    # Bounded concurrency actually happened: >1 in flight, never above the cap.
    assert 1 < fake.max_in_flight <= 8
    out = capsys.readouterr().out
    assert "OK" in out and "MISMATCH" not in out


def test_download_error_aborts_run_and_rerun_completes(tmp_path):
    objects = {
        f"{LANCE}tbl/{i:04d}.bin": f"payload-{i:04d}".encode() for i in range(30)
    }
    bad = f"{LANCE}tbl/0013.bin"
    fake = FakeS3(objects, download_delay=0.002, fail_keys={bad})

    # First download exception aborts the run un-swallowed (queued futures
    # are cancelled; boto3-style partial writes may remain on disk).
    with pytest.raises(RuntimeError, match="injected download failure"):
        replica.bootstrap(tmp_path, dry_run=False, client=fake, workers=8)
    assert (
        tmp_path / ".evidence/lance/tbl/0013.bin"
    ).read_bytes() == b"partial-write-then-died"

    # Fresh run with the fault cleared: completed files resume-skip, the
    # partial write is a size mismatch -> re-downloaded, run goes green.
    fake.fail_keys.clear()
    report = replica.bootstrap(tmp_path, dry_run=False, client=fake, workers=8)

    assert report["ok"] is True
    assert bad in fake.downloads
    for key, content in objects.items():
        assert (
            tmp_path / ".evidence/lance" / key[len(LANCE) :]
        ).read_bytes() == content
