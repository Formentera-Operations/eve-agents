"""Evidence retrieval: hybrid bundle and direct modes (U4, KTD7).

Modes mirror the reference implementation:

- ``chunks`` / ``pages``: gateway-embedded text vector search.
- ``fts``: BM25 full-text over chunks.
- ``images``: CLIP text-to-image over page screenshots.
- ``assets``: CLIP text-to-image over extracted figures.
- ``hybrid_bundle`` (default): the text searches plus the figure search run
  together and merge by page identity with reciprocal-rank fusion — each
  page wins on its strongest signals, and the hit reports which signals
  fired.

Grep is a true substring/regex scan over stored text columns. FTS never
gates grep results — BM25 tokenization silently drops alphanumeric codes
like ``S733H`` (KTD7), so exactness comes from a real scan.

Image columns are never selected in search paths (see store.py's KTD2
divergence note); screenshot bytes come only from `get_page(...,
include_screenshot=True)`.
"""

import re
from dataclasses import dataclass, field

from doc_intel_analysts.evidence.store import EvidenceStore

HIT_COLUMNS = ["page_id", "doc_id", "page_num", "s3key", "asset_team"]
RRF_K = 60

TEXT_MODES = ("chunks", "pages", "fts")
IMAGE_MODES = ("images", "assets")
ALL_MODES = ("hybrid_bundle", *TEXT_MODES, *IMAGE_MODES)


@dataclass
class PageHit:
    page_id: str
    doc_id: str
    page_num: int
    s3key: str
    asset_team: str
    score: float
    signals: dict[str, int] = field(default_factory=dict)  # mode -> best rank (1-based)
    snippet: str = ""

    def to_dict(self) -> dict:
        return {
            "page_id": self.page_id,
            "doc_id": self.doc_id,
            "page_num": self.page_num,
            "s3key": self.s3key,
            "asset_team": self.asset_team,
            "score": round(self.score, 4),
            "signals": self.signals,
            "snippet": self.snippet,
        }


class EvidenceRetriever:
    def __init__(self, store: EvidenceStore, *, query_embedder=None):
        from doc_intel_analysts.evidence.store import GatewayTextEmbedder

        self._store = store
        self._query_embedder = query_embedder or GatewayTextEmbedder(store._config)

    # -- search ------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        mode: str = "hybrid_bundle",
        limit: int = 5,
        asset_team: str | None = None,
    ) -> list[PageHit]:
        if mode not in ALL_MODES:
            raise ValueError(f"unknown mode {mode!r}; expected one of {ALL_MODES}")
        pool = limit * 3 if mode == "hybrid_bundle" else limit
        ranked_lists: dict[str, list[dict]] = {}

        if mode in ("hybrid_bundle", "chunks", "pages"):
            vector = self._query_embedder([query])[0]
            if mode in ("hybrid_bundle", "chunks"):
                ranked_lists["chunks"] = self._vector_search(
                    "chunks", vector, "vector", pool, asset_team, with_text=True
                )
            if mode in ("hybrid_bundle", "pages"):
                ranked_lists["pages"] = self._vector_search(
                    "pages", vector, "vector", pool, asset_team
                )
        if mode in ("hybrid_bundle", "fts"):
            ranked_lists["fts"] = self._fts_search("chunks", query, pool, asset_team)
        if mode in ("hybrid_bundle", "images", "assets"):
            clip_vector = self._store.image_embedder.embed_text(query)
            if mode in ("hybrid_bundle", "images"):
                ranked_lists["images"] = self._clip_search(
                    "pages", clip_vector, pool, asset_team
                )
            if mode == "assets":
                ranked_lists["assets"] = self._clip_search(
                    "assets", clip_vector, pool, asset_team
                )

        return self._fuse(ranked_lists, limit)

    def _where(self, asset_team: str | None) -> str | None:
        if not asset_team:
            return None
        return f"asset_team = '{asset_team.replace(chr(39), chr(39) * 2)}'"

    @staticmethod
    def _like_literal(fragment: str) -> str:
        """Escape a fragment for literal use inside a LIKE pattern: quotes
        doubled for the SQL literal, and LIKE wildcards (%, _, \\) escaped so
        filename underscores don't act as single-character wildcards. Pair
        with ESCAPE '\\' on the LIKE clause."""
        return (
            fragment.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
            .replace("'", "''")
            .lower()
        )

    def _fragment_clause(self, name_query: str) -> str | None:
        """Case-insensitive contiguous-fragment match on s3key, treating the
        fragment literally (see _like_literal)."""
        if not name_query:
            return None
        return f"lower(s3key) LIKE '%{self._like_literal(name_query)}%' ESCAPE '\\'"

    def _vector_search(
        self, table, vector, column, limit, asset_team, *, with_text=False
    ) -> list[dict]:
        columns = HIT_COLUMNS + (["text"] if with_text else [])
        q = (
            self._store.table(table)
            .search(vector, vector_column_name=column)
            .select(columns)
            .limit(limit)
        )
        where = self._where(asset_team)
        if where:
            q = q.where(where)
        return q.to_list()

    def _clip_search(self, table, vector, limit, asset_team) -> list[dict]:
        q = (
            self._store.table(table)
            .search(vector, vector_column_name="clip_vector")
            .select(HIT_COLUMNS)
            .limit(limit)
        )
        clauses = []
        where = self._where(asset_team)
        if where:
            clauses.append(where)
        if table == "pages":
            # pages without screenshots carry zero clip vectors; prefilter
            clauses.append("has_screenshot = true")
        if clauses:
            q = q.where(" AND ".join(clauses))
        return q.to_list()

    def _fts_search(self, table, query, limit, asset_team) -> list[dict]:
        try:
            q = (
                self._store.table(table)
                .search(query, query_type="fts")
                .select(HIT_COLUMNS + ["text"])
                .limit(limit)
            )
            where = self._where(asset_team)
            if where:
                q = q.where(where)
            return q.to_list()
        except Exception:  # noqa: BLE001 — no FTS index yet (empty store)
            return []

    def _fuse(self, ranked_lists: dict[str, list[dict]], limit: int) -> list[PageHit]:
        """Merge by page_id, each page winning on its STRONGEST signal (KTD7).

        Primary score is the reciprocal rank of the page's best rank across
        signals; agreement across signals adds only a small tie-break. A
        summed fusion was tried first and failed live: a decisive rank-1 FTS
        hit was drowned by pages that appeared mid-list in three signals.
        """
        hits: dict[str, PageHit] = {}
        for signal, rows in ranked_lists.items():
            for rank, row in enumerate(rows, 1):
                pid = row["page_id"]
                hit = hits.get(pid)
                if hit is None:
                    hit = PageHit(
                        page_id=pid,
                        doc_id=row["doc_id"],
                        page_num=row["page_num"],
                        s3key=row["s3key"],
                        asset_team=row["asset_team"],
                        score=0.0,
                    )
                    hits[pid] = hit
                if signal not in hit.signals or rank < hit.signals[signal]:
                    hit.signals[signal] = rank
                text = row.get("text", "")
                if text and (not hit.snippet or len(text) < len(hit.snippet)):
                    hit.snippet = text[:400]
        for hit in hits.values():
            best = min(hit.signals.values())
            agreement = sum(1.0 / (RRF_K + r) for r in hit.signals.values())
            hit.score = 1.0 / (RRF_K + best) + 0.01 * agreement
        return sorted(hits.values(), key=lambda h: -h.score)[:limit]

    # -- grep --------------------------------------------------------------

    def grep(
        self,
        pattern: str,
        *,
        regex: bool = False,
        limit: int = 20,
        asset_team: str | None = None,
    ) -> list[dict]:
        """Exact substring (default) or regex scan over page text.

        A filtered column scan, deliberately not FTS-gated: tokenizers drop
        well codes like 'S733H'; a scan cannot.
        """
        expression = pattern if regex else re.escape(pattern)
        matcher = re.compile(expression)
        # Filter pushdown, not a Python table scan: raw-dataset to_batches()
        # panics in Rust on this store under the pinned lancedb/pylance combo
        # (same family as the take_blobs panic — see store.py). regexp_like
        # runs the same Rust regex engine inside the query.
        clauses = [f"regexp_like(text, '{expression.replace(chr(39), chr(39) * 2)}')"]
        where = self._where(asset_team)
        if where:
            clauses.append(where)
        rows = (
            self._store.table("pages")
            .search()
            .where(" AND ".join(clauses))
            .select(["page_id", "doc_id", "page_num", "s3key", "asset_team", "text"])
            .limit(limit)
            .to_list()
        )
        results = []
        for row in rows:
            match = matcher.search(row["text"])
            if not match:
                continue
            start = max(0, match.start() - 150)
            results.append(
                {
                    "page_id": row["page_id"],
                    "doc_id": row["doc_id"],
                    "page_num": row["page_num"],
                    "s3key": row["s3key"],
                    "asset_team": row["asset_team"],
                    "match": match.group(0),
                    "context": row["text"][start : match.end() + 150],
                }
            )
        return results

    # -- find / read -------------------------------------------------------

    def find_documents(
        self,
        name_query: str = "",
        *,
        asset_team: str | None = None,
        format_gate: str | None = None,
        limit: int = 25,
    ) -> list[dict]:
        """Documents-table lookup by filename fragment / team / format.

        Complements the manifest tool: covers Westlake files the sample
        manifest lacks.
        """
        clauses = []
        fragment = self._fragment_clause(name_query)
        if fragment:
            clauses.append(fragment)
        where = self._where(asset_team)
        if where:
            clauses.append(where)
        if format_gate:
            clauses.append(f"format_gate = '{format_gate.replace(chr(39), chr(39) * 2)}'")
        q = self._store.table("documents").search().limit(limit)
        if clauses:
            q = q.where(" AND ".join(clauses))
        return q.to_list()

    def document_status(
        self,
        name_query: str = "",
        *,
        asset_team: str | None = None,
        status: str | None = None,
        limit: int = 25,
    ) -> dict:
        """Ingest-ledger lookup: per-document status with reasons.

        The ledger is the coverage source of truth — complete rows are
        indexed, skipped rows were deliberately declined (format gate or
        deterministic image verdict), failed rows re-run every pass.
        `will_retry` mirrors needs_ingest's settled test from the ledger
        side: a row is settled only when its status is complete/skipped AND
        it carries a non-empty checksum. Terminality is per-checksum — a
        changed upstream file re-ingests regardless. Strictly read-only.

        The ledger has no asset_team column: the team filter is an s3key
        prefix match on `{team}/` (the archive layout), which is also why
        returned rows carry no separate asset-team field.
        """
        clauses = []
        fragment = self._fragment_clause(name_query)
        if fragment:
            clauses.append(fragment)
        if asset_team:
            team = self._like_literal(asset_team.rstrip("/"))
            clauses.append(f"lower(s3key) LIKE '{team}/%' ESCAPE '\\'")
        if status:
            clauses.append(f"status = '{status.replace(chr(39), chr(39) * 2)}'")
        where = " AND ".join(clauses) if clauses else None

        ledger = self._store.table("ledger")
        # Freshness watermark over the whole ledger (proxy for the last
        # ingest pass) — computed FIRST so, under a concurrent ingest, it can
        # only understate the freshness of the rows and counts read after it.
        # Present on every response, including empty ones, so absence claims
        # can be dated.
        stamps = ledger.search().select(["updated_at"]).limit(None).to_list()
        ledger_as_of = max((r["updated_at"] for r in stamps), default=None)
        summary = {
            s: ledger.count_rows(
                f"status = '{s}'" if where is None else f"({where}) AND status = '{s}'"
            )
            for s in ("complete", "skipped", "failed")
        }
        q = ledger.search().select(
            ["doc_id", "s3key", "checksum", "status", "reason",
             "page_count", "updated_at"]
        ).limit(limit)
        if where:
            q = q.where(where)
        matches = []
        for row in q.to_list():
            checksum = row.pop("checksum", "")
            row["will_retry"] = row["status"] == "failed" or not checksum
            matches.append(row)

        return {
            "matches": matches,
            "summary": summary,
            "total_matches": sum(summary.values()),
            "ledger_as_of": ledger_as_of,
        }

    def get_page(
        self, page_id: str, *, include_screenshot: bool = False
    ) -> dict | None:
        columns = HIT_COLUMNS + ["text", "has_screenshot", "width", "height"]
        if include_screenshot:
            columns.append("screenshot")
        safe = page_id.replace("'", "''")
        rows = (
            self._store.table("pages")
            .search()
            .where(f"page_id = '{safe}'")
            .select(columns)
            .to_list()
        )
        if not rows:
            return None
        row = rows[0]
        if include_screenshot:
            row["screenshot"] = bytes(row["screenshot"]) or None
        return row

    def get_document_pages(self, doc_id: str) -> list[dict]:
        safe = doc_id.replace("'", "''")
        return (
            self._store.table("pages")
            .search()
            .where(f"doc_id = '{safe}'")
            .select(HIT_COLUMNS + ["text"])
            .limit(10**4)
            .to_list()
        )
