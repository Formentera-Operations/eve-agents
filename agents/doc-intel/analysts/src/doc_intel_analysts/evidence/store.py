"""LanceDB evidence store: five page-keyed tables with vectors and blobs (U3).

Schema follows `lancedb/liteparse-lancedb-pdf-qa` (KTD2), with corpus keys as
identity: `documents`, `pages`, `chunks`, `assets`, and the ingest `ledger`.
`page_id = {doc_id}:p{page_num}` joins everything; every row carries its
`s3key` so hits map straight back to provenance.

Embedding paths (KTD3): text via the AI Gateway (config-guarded, batched),
images via local OpenCLIP. Both are injectable for tests.

Idempotency and crash-safety (KTD6): per-document delete-before-insert, and
the ledger row is written LAST — a crash mid-document leaves the ledger
without a `complete` row, so the next run redoes that document cleanly.

KTD2 divergence, forced by the pinned versions: image columns are plain
`large_binary`, NOT `lance-encoding:blob`. The blob read path
(`Dataset.take_blobs`) panics in Rust for tables created through
lancedb==0.34.0 + pylance 0.36 (verified 2026-07-06, any blob size, all
three addressing modes), and the lancedb pin is fixed to cognee's
resolution. Plain binary round-trips correctly; the discipline is that
every query path SELECTs away image columns unless bytes were asked for —
Lance v2 late materialization then keeps scans cheap.

Concurrency (R13, verified empirically in tests): LanceDB uses MVCC
versioned writes — a reader opened during an active ingest write sees the
last committed version and never blocks or errors; new rows appear on the
next query after commit. No Kuzu-style single-writer constraint. The one
rule: don't run two ingest processes against the same store concurrently
(last-writer-wins on ledger rows would double work, not corrupt data).
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

import pyarrow as pa

from doc_intel_analysts.evidence.config import EvidenceConfig
from doc_intel_analysts.evidence.parse import ParsedDocument, SkipRecord

CLIP_DIMENSIONS = 512
TEXT_EMBED_BATCH = 96

def _schemas(text_dims: int) -> dict[str, pa.Schema]:
    text_vec = pa.list_(pa.float32(), text_dims)
    clip_vec = pa.list_(pa.float32(), CLIP_DIMENSIONS)
    return {
        "documents": pa.schema(
            [
                pa.field("doc_id", pa.string()),
                pa.field("s3key", pa.string()),
                pa.field("asset_team", pa.string()),
                pa.field("format_gate", pa.string()),
                pa.field("page_count", pa.int32()),
            ]
        ),
        "pages": pa.schema(
            [
                pa.field("page_id", pa.string()),
                pa.field("doc_id", pa.string()),
                pa.field("page_num", pa.int32()),
                pa.field("s3key", pa.string()),
                pa.field("asset_team", pa.string()),
                pa.field("text", pa.string()),
                pa.field("vector", text_vec),
                pa.field("clip_vector", clip_vec),
                pa.field("has_screenshot", pa.bool_()),
                pa.field("screenshot", pa.large_binary()),
                pa.field("width", pa.int32()),
                pa.field("height", pa.int32()),
            ]
        ),
        "chunks": pa.schema(
            [
                pa.field("chunk_id", pa.string()),
                pa.field("page_id", pa.string()),
                pa.field("doc_id", pa.string()),
                pa.field("page_num", pa.int32()),
                pa.field("s3key", pa.string()),
                pa.field("asset_team", pa.string()),
                pa.field("text", pa.string()),
                pa.field("vector", text_vec),
            ]
        ),
        "assets": pa.schema(
            [
                pa.field("asset_id", pa.string()),
                pa.field("page_id", pa.string()),
                pa.field("doc_id", pa.string()),
                pa.field("page_num", pa.int32()),
                pa.field("s3key", pa.string()),
                pa.field("asset_team", pa.string()),
                pa.field("kind", pa.string()),
                pa.field("image", pa.large_binary()),
                pa.field("clip_vector", clip_vec),
            ]
        ),
        "ledger": pa.schema(
            [
                pa.field("doc_id", pa.string()),
                pa.field("s3key", pa.string()),
                pa.field("checksum", pa.string()),
                pa.field("status", pa.string()),  # complete | skipped | failed
                pa.field("reason", pa.string()),
                pa.field("page_count", pa.int32()),
                pa.field("chunk_count", pa.int32()),
                pa.field("asset_count", pa.int32()),
                pa.field("updated_at", pa.string()),
            ]
        ),
    }


def checksum_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class GatewayTextEmbedder:
    """Batched text embeddings through the Vercel AI Gateway.

    The endpoint was validated by the config egress guard before this class
    can exist; this class never reads endpoint env itself.
    """

    def __init__(self, config: EvidenceConfig):
        from openai import OpenAI

        self._client = OpenAI(
            base_url=config.gateway_base_url, api_key=config.gateway_api_key
        )
        self._model = config.embedding_model
        self._dims = config.embedding_dimensions

    def __call__(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), TEXT_EMBED_BATCH):
            batch = [t[:8000] or " " for t in texts[start : start + TEXT_EMBED_BATCH]]
            response = self._client.embeddings.create(model=self._model, input=batch)
            vectors.extend(item.embedding for item in response.data)
        return vectors


class ClipImageEmbedder:
    """Local OpenCLIP image embeddings — no document-content egress."""

    def __init__(self, config: EvidenceConfig):
        self._config = config
        self._model = None
        self._preprocess = None

    def _device(self):
        import torch

        return "mps" if torch.backends.mps.is_available() else "cpu"

    def _ensure_model(self):
        if self._model is None:
            import open_clip

            self._model, _, self._preprocess = open_clip.create_model_and_transforms(
                self._config.clip_model, pretrained=self._config.clip_pretrained
            )
            self._model.eval()
            self._model.to(self._device())
        return self._model, self._preprocess

    def __call__(self, images: list[bytes]) -> list[list[float]]:
        import io

        import torch
        from PIL import Image

        model, preprocess = self._ensure_model()
        with torch.no_grad():
            batch = torch.stack(
                [
                    preprocess(Image.open(io.BytesIO(data)).convert("RGB"))
                    for data in images
                ]
            ).to(self._device())
            feats = model.encode_image(batch)
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.cpu().tolist()

    def embed_text(self, query: str) -> list[float]:
        """CLIP text tower, for text-to-image retrieval (U4)."""
        import open_clip
        import torch

        model, _ = self._ensure_model()
        tokenizer = open_clip.get_tokenizer(self._config.clip_model)
        with torch.no_grad():
            feats = model.encode_text(tokenizer([query]).to(self._device()))
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats[0].cpu().tolist()


_ZERO_CLIP = [0.0] * CLIP_DIMENSIONS


@dataclass
class IngestOutcome:
    doc_id: str
    status: str  # complete | skipped | failed | unchanged
    reason: str = ""


class EvidenceStore:
    """Application-owned store at `.evidence/lance/` — never inside `.cognee/`."""

    def __init__(
        self,
        config: EvidenceConfig,
        *,
        text_embedder=None,
        image_embedder=None,
    ):
        import lancedb

        self._config = config
        self._db = lancedb.connect(config.lance_root)
        self._text_embedder = text_embedder or GatewayTextEmbedder(config)
        self._image_embedder = image_embedder or ClipImageEmbedder(config)
        self._tables = {}
        existing = self._db.list_tables().tables
        for name, schema in _schemas(config.embedding_dimensions).items():
            if name in existing:
                self._tables[name] = self._db.open_table(name)
            else:
                self._tables[name] = self._db.create_table(name, schema=schema)

    def table(self, name: str):
        return self._tables[name]

    @property
    def image_embedder(self):
        return self._image_embedder

    def ledger_status(self, doc_id: str) -> dict | None:
        rows = (
            self.table("ledger").search().where(f"doc_id = '{doc_id}'").to_list()
        )
        return rows[0] if rows else None

    def ledger_snapshot(self) -> dict[str, dict]:
        """Full ledger read keyed by doc_id, for resume fast-forward.

        One scan replaces per-doc where-scans, which cost ~0.14s each at
        Westlake fragment counts — ~35 min of silent resume per pass
        (measured 2026-07-08). Point-in-time: valid because each doc
        appears at most once per pass (single writer, deduped listing).
        """
        rows = (
            self.table("ledger")
            .search()
            .select(["doc_id", "status", "checksum"])
            .to_list()
        )
        return {row["doc_id"]: row for row in rows}

    def needs_ingest(
        self, doc_id: str, checksum: str, *, ledger: dict[str, dict] | None = None
    ) -> bool:
        """Ledger short-circuit: `complete` and `skipped` rows with a
        matching checksum skip work — failed/interrupted docs re-run.
        (Skips are format-gate verdicts; unchanged bytes can't change them.)
        Pass `ledger` (from ledger_snapshot) to avoid a per-doc table scan."""
        row = self.ledger_status(doc_id) if ledger is None else ledger.get(doc_id)
        if row is None:
            return True
        return not (
            row["status"] in ("complete", "skipped")
            and checksum
            and row["checksum"] == checksum
        )

    def upsert_document(self, doc: ParsedDocument, checksum: str) -> IngestOutcome:
        """Write one parsed document. Delete-before-insert, ledger LAST.

        Deletes are skipped for first-seen documents: every delete() is a
        table commit, and at Westlake scale the per-doc delete storm was the
        dominant disk cost (~10 versions/doc, 1.9GB of ledger manifests for
        KB of live rows — measured 2026-07-07).
        """
        prior = self.ledger_status(doc.doc_id)
        if prior is not None and prior["status"] == "complete" and prior["checksum"] == checksum:
            return IngestOutcome(doc_id=doc.doc_id, status="unchanged")
        try:
            if prior is not None:
                self._delete_document_rows(doc.doc_id)
            self._insert_rows(doc)
        except Exception as exc:  # noqa: BLE001 — failures must reach the ledger
            self._write_ledger(
                doc.doc_id, doc.s3key, checksum, "failed", f"ingest error: {exc}",
                doc, delete_prior=prior is not None,
            )
            return IngestOutcome(doc.doc_id, "failed", str(exc))
        self._write_ledger(
            doc.doc_id, doc.s3key, checksum, "complete", "", doc,
            delete_prior=prior is not None,
        )
        return IngestOutcome(doc_id=doc.doc_id, status="complete")

    def record_skip(self, skip: SkipRecord, checksum: str = "") -> IngestOutcome:
        prior = self.ledger_status(skip.doc_id)
        if prior is not None:
            self._delete_document_rows(skip.doc_id)
        self._write_ledger(
            skip.doc_id, skip.s3key, checksum, "skipped", skip.reason,
            delete_prior=prior is not None,
        )
        return IngestOutcome(doc_id=skip.doc_id, status="skipped", reason=skip.reason)

    def _delete_document_rows(self, doc_id: str) -> None:
        predicate = f"doc_id = '{doc_id}'"
        for name in ("documents", "pages", "chunks", "assets", "ledger"):
            self.table(name).delete(predicate)

    def _insert_rows(self, doc: ParsedDocument) -> None:
        self.table("documents").add(
            [
                {
                    "doc_id": doc.doc_id,
                    "s3key": doc.s3key,
                    "asset_team": doc.asset_team,
                    "format_gate": doc.format_gate,
                    "page_count": doc.page_count,
                }
            ]
        )

        page_texts = [p.text for p in doc.pages if p.text.strip()]
        chunk_texts = [c.text for c in doc.chunks]
        text_vectors = (
            self._text_embedder(page_texts + chunk_texts)
            if page_texts or chunk_texts
            else []
        )
        page_vectors = dict(
            zip([p.page_id for p in doc.pages if p.text.strip()], text_vectors)
        )
        chunk_vectors = text_vectors[len(page_texts) :]

        shots = [p for p in doc.pages if p.screenshot_jpeg]
        clip_by_page = dict(
            zip(
                [p.page_id for p in shots],
                self._image_embedder([p.screenshot_jpeg for p in shots])
                if shots
                else [],
            )
        )

        zero_text = [0.0] * self._config.embedding_dimensions
        self.table("pages").add(
            [
                {
                    "page_id": p.page_id,
                    "doc_id": p.doc_id,
                    "page_num": p.page_num,
                    "s3key": doc.s3key,
                    "asset_team": doc.asset_team,
                    "text": p.text,
                    "vector": page_vectors.get(p.page_id, zero_text),
                    "clip_vector": clip_by_page.get(p.page_id, _ZERO_CLIP),
                    "has_screenshot": p.screenshot_jpeg is not None,
                    "screenshot": p.screenshot_jpeg or b"",
                    "width": p.width,
                    "height": p.height,
                }
                for p in doc.pages
            ]
        )

        if doc.chunks:
            self.table("chunks").add(
                [
                    {
                        "chunk_id": c.chunk_id,
                        "page_id": c.page_id,
                        "doc_id": c.doc_id,
                        "page_num": c.page_num,
                        "s3key": doc.s3key,
                        "asset_team": doc.asset_team,
                        "text": c.text,
                        "vector": vec,
                    }
                    for c, vec in zip(doc.chunks, chunk_vectors)
                ]
            )

        if doc.assets:
            asset_clip = self._image_embedder([a.image_jpeg for a in doc.assets])
            self.table("assets").add(
                [
                    {
                        "asset_id": a.asset_id,
                        "page_id": a.page_id,
                        "doc_id": a.doc_id,
                        "page_num": a.page_num,
                        "s3key": doc.s3key,
                        "asset_team": doc.asset_team,
                        "kind": a.kind,
                        "image": a.image_jpeg,
                        "clip_vector": vec,
                    }
                    for a, vec in zip(doc.assets, asset_clip)
                ]
            )

    def _write_ledger(
        self,
        doc_id: str,
        s3key: str,
        checksum: str,
        status: str,
        reason: str,
        doc: ParsedDocument | None = None,
        *,
        delete_prior: bool = True,
    ) -> None:
        if delete_prior:
            self.table("ledger").delete(f"doc_id = '{doc_id}'")
        self.table("ledger").add(
            [
                {
                    "doc_id": doc_id,
                    "s3key": s3key,
                    "checksum": checksum,
                    "status": status,
                    "reason": reason,
                    "page_count": doc.page_count if doc else 0,
                    "chunk_count": len(doc.chunks) if doc else 0,
                    "asset_count": len(doc.assets) if doc else 0,
                    "updated_at": _now(),
                }
            ]
        )

    def build_indexes(self) -> None:
        """FTS on text columns, BTree on prefilter columns. Safe to re-run.

        Called at the end of an ingest run, not per-document — index builds
        scan the table.
        """
        from lancedb.index import FTS, BTree

        for name, column in (("chunks", "text"), ("pages", "text")):
            table = self.table(name)
            if table.count_rows() == 0:
                continue
            table.create_index(column, config=FTS(), replace=True)
            table.create_index("asset_team", config=BTree(), replace=True)
            table.create_index("doc_id", config=BTree(), replace=True)

    def counts(self) -> dict[str, int]:
        return {name: t.count_rows() for name, t in self._tables.items()}

    def optimize(self, table_names: list[str] | None = None) -> None:
        """Compact fragments and drop old MVCC versions.

        Delete-before-insert writes a new table version per document; the
        ledger and documents tables accumulate dead versions linearly with
        ingest volume (~2 GB observed at 2,500 Westlake docs). Mid-pass, pass
        `["documents", "ledger"]` to bound that churn without compacting the
        multi-GB pages/chunks tables (the 2026-07-07/08 memory chokes both hit
        during full-store maintenance); full compaction runs at end of pass.
        """
        from datetime import timedelta

        tables = (
            self._tables.values()
            if table_names is None
            else [self._tables[name] for name in table_names]
        )
        for table in tables:
            table.optimize(cleanup_older_than=timedelta(0))
