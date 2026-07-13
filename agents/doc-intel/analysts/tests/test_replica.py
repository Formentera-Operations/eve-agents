"""U5 contract tests: bootstrap replica sync (dry-run plan, skip logic, verify).

Thin by design — stubbed S3 client, temp dirs, no network. The real proof
is the gate run in Azure.
"""

import hashlib
from pathlib import Path

import pytest

from doc_intel_analysts.evidence import replica

LANCE = f"{replica.EVIDENCE_PREFIX}/lance/"
PARSED = f"{replica.EVIDENCE_PREFIX}/parsed/"
COGNEE = f"{replica.EVIDENCE_PREFIX}/cognee/"
MASTERS = f"{replica.EVIDENCE_PREFIX}/masters/"


class FakeS3:
    """In-memory stand-in for the two client methods replica uses."""

    def __init__(
        self,
        objects: dict[str, bytes],
        *,
        multipart: set[str] | None = None,
        listed_size_override: dict[str, int] | None = None,
    ):
        self.objects = objects
        self.multipart = multipart or set()
        self.listed_size_override = listed_size_override or {}
        self.downloads: list[str] = []

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
        self.downloads.append(key)
        Path(filename).write_bytes(self.objects[key])


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


def test_skip_up_to_date_and_redownload_mismatches(tmp_path):
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

    report = replica.bootstrap(tmp_path, dry_run=False, client=fake)

    assert sorted(fake.downloads) == sorted([short, drift])
    assert (tmp_path / ".evidence/lance/tbl/short.bin").read_bytes() == (
        b"full-remote-content"
    )
    assert (tmp_path / ".evidence/parsed/drift.json").read_bytes() == b"remote-json"
    assert (tmp_path / ".masters/big.csv").read_bytes() == b"XXXXXXX-abc"
    assert report["ok"] is True
    assert all(v["ok"] for v in report["verification"])


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
