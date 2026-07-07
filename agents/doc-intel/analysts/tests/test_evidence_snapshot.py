"""U8 contract test: snapshot round-trip on a fixture store."""

import pytest

from doc_intel_analysts.evidence import parse, snapshot, store
from doc_intel_analysts.evidence.config import EvidenceConfig


class LocalS3:
    """In-memory stand-in exposing the four client methods snapshot uses."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def upload_file(self, filename, bucket, key):
        self.objects[key] = open(filename, "rb").read()

    def download_file(self, bucket, key, filename):
        open(filename, "wb").write(self.objects[key])

    def put_object(self, Bucket, Key, Body):
        self.objects[Key] = Body

    def get_paginator(self, name):
        objects = self.objects

        class Paginator:
            def paginate(self, Bucket, Prefix):
                yield {
                    "Contents": [
                        {"Key": k} for k in sorted(objects) if k.startswith(Prefix)
                    ]
                }

        return Paginator()


def make_store(tmp_path):
    cfg = EvidenceConfig(
        gateway_base_url="https://ai-gateway.vercel.sh/v1",
        gateway_api_key="test-key",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=8,
        clip_model="ViT-B-32-quickgelu",
        clip_pretrained="openai",
        store_root=tmp_path / ".evidence",
        lance_root=tmp_path / ".evidence" / "lance",
        parsed_root=tmp_path / ".evidence" / "parsed",
    )
    cfg.lance_root.mkdir(parents=True, exist_ok=True)
    return cfg, store.EvidenceStore(
        cfg,
        text_embedder=lambda texts: [[1.0] * 8 for _ in texts],
        image_embedder=lambda images: [[0.5] * store.CLIP_DIMENSIONS for _ in images],
    )


def test_snapshot_round_trip(tmp_path):
    cfg, st = make_store(tmp_path / "src")
    doc = parse.parse_document("t/w/a.las", b"DEPT GR\n9800 45\n" * 50, None)
    st.upsert_document(doc, "sum1")

    client = LocalS3()
    manifest = snapshot.publish(cfg.lance_root, stamp="test-stamp", client=client)
    assert manifest["files"] > 0 and manifest["stamp"] == "test-stamp"
    assert f"{snapshot.SNAPSHOT_PREFIX}/test-stamp/_snapshot.json" in client.objects

    dest = tmp_path / "restored"
    result = snapshot.restore("test-stamp", dest, client=client)
    assert result["files"] == manifest["files"]

    import lancedb

    restored = lancedb.connect(dest)
    rows = restored.open_table("pages").search().where(
        f"doc_id = '{doc.doc_id}'"
    ).to_list()
    assert len(rows) == 1 and rows[0]["text"].startswith("DEPT GR")


def test_publish_empty_store_refuses(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(RuntimeError, match="nothing to snapshot"):
        snapshot.publish(empty, client=LocalS3())


def test_restore_unknown_stamp_refuses(tmp_path):
    with pytest.raises(RuntimeError, match="no snapshot found"):
        snapshot.restore("nope", tmp_path / "d", client=LocalS3())
