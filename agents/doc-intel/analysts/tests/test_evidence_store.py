"""U3 contract tests: round-trip, idempotency, resume, batching, concurrency."""

import threading

import pytest

from doc_intel_analysts.evidence import parse, store
from doc_intel_analysts.evidence.config import EvidenceConfig


def make_config(tmp_path, dims=8) -> EvidenceConfig:
    return EvidenceConfig(
        gateway_base_url="https://ai-gateway.vercel.sh/v1",
        gateway_api_key="test-key",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=dims,
        clip_model="ViT-B-32-quickgelu",
        clip_pretrained="openai",
        store_root=tmp_path / ".evidence",
        lance_root=tmp_path / ".evidence" / "lance",
        parsed_root=tmp_path / ".evidence" / "parsed",
    )


def fake_text_embedder(dims=8):
    def embed(texts):
        return [[float(len(t) % 7)] * dims for t in texts]

    return embed


def fake_image_embedder():
    def embed(images):
        return [[0.5] * store.CLIP_DIMENSIONS for _ in images]

    return embed


def make_store(tmp_path, dims=8):
    cfg = make_config(tmp_path, dims)
    cfg.lance_root.mkdir(parents=True, exist_ok=True)
    cfg.parsed_root.mkdir(parents=True, exist_ok=True)
    return store.EvidenceStore(
        cfg,
        text_embedder=fake_text_embedder(dims),
        image_embedder=fake_image_embedder(),
    )


def make_doc(key="team/well/doc.las", text="DEPT GR\n9800 45\n" * 100):
    doc = parse.parse_document(key, text.encode(), None, asset_team="team")
    assert isinstance(doc, parse.ParsedDocument)
    return doc


def test_round_trip_by_page_id(tmp_path):
    st = make_store(tmp_path)
    doc = make_doc()
    outcome = st.upsert_document(doc, "sum1")
    assert outcome.status == "complete"
    pid = doc.pages[0].page_id
    pages = st.table("pages").search().where(f"page_id = '{pid}'").to_list()
    assert len(pages) == 1 and pages[0]["s3key"] == doc.s3key
    chunks = st.table("chunks").search().where(f"page_id = '{pid}'").to_list()
    assert len(chunks) == len(doc.chunks)
    ledger = st.ledger_status(doc.doc_id)
    assert ledger["status"] == "complete" and ledger["checksum"] == "sum1"


def tiny_jpeg() -> bytes:
    import io

    from PIL import Image

    img = Image.new("RGB", (64, 48), (200, 30, 30))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


def test_blob_bytes_intact(tmp_path):
    st = make_store(tmp_path)
    doc = parse.parse_document("t/w/plat.jpg", tiny_jpeg(), None)
    st.upsert_document(doc, "sum1")
    row = st.table("pages").search().where(f"doc_id = '{doc.doc_id}'").to_list()[0]
    assert bytes(row["screenshot"]) == doc.pages[0].screenshot_jpeg


def test_idempotent_second_run_writes_nothing(tmp_path):
    st = make_store(tmp_path)
    doc = make_doc()
    st.upsert_document(doc, "sum1")
    assert st.upsert_document(doc, "sum1").status == "unchanged"
    assert st.table("chunks").count_rows() == len(doc.chunks)
    # changed content re-ingests without duplication
    assert st.upsert_document(doc, "sum2").status == "complete"
    assert st.table("chunks").count_rows() == len(doc.chunks)


def test_interrupted_doc_completes_on_rerun(tmp_path):
    st = make_store(tmp_path)
    doc = make_doc()
    # Simulate a crash after parse but before completion: ledger row exists
    # with a non-complete status.
    st.table("ledger").add(
        [
            {
                "doc_id": doc.doc_id,
                "s3key": doc.s3key,
                "checksum": "sum1",
                "status": "failed",
                "reason": "embed-pending (interrupted)",
                "page_count": 0,
                "chunk_count": 0,
                "asset_count": 0,
                "updated_at": "",
            }
        ]
    )
    assert st.needs_ingest(doc.doc_id, "sum1") is True
    assert st.upsert_document(doc, "sum1").status == "complete"
    assert st.ledger_status(doc.doc_id)["status"] == "complete"


def test_gateway_embedder_batches(monkeypatch, tmp_path):
    calls = []

    class FakeEmbeddings:
        def create(self, model, input):
            calls.append(len(input))
            return type(
                "R",
                (),
                {
                    "data": [
                        type("D", (), {"embedding": [0.0] * 8})() for _ in input
                    ]
                },
            )()

    class FakeOpenAI:
        def __init__(self, base_url, api_key):
            self.embeddings = FakeEmbeddings()

    import openai

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    embedder = store.GatewayTextEmbedder(make_config(tmp_path))
    vectors = embedder([f"text {i}" for i in range(200)])
    assert len(vectors) == 200
    assert calls == [96, 96, 8], "batched, not per-chunk"


def test_skip_recorded_in_ledger(tmp_path):
    st = make_store(tmp_path)
    skip = parse.parse_document("t/w/costs.xlsx", b"PK", None)
    st.record_skip(skip, "sum1")
    row = st.ledger_status(skip.doc_id)
    assert row["status"] == "skipped" and "excel-family" in row["reason"]


def test_concurrent_read_during_write(tmp_path):
    """R13: a service-style reader during active ingest writes must not
    corrupt or block. LanceDB MVCC — readers see committed versions."""
    st = make_store(tmp_path)
    st.upsert_document(make_doc("t/w/first.las"), "sum0")
    errors = []

    def writer():
        try:
            for i in range(5):
                st.upsert_document(make_doc(f"t/w/doc{i}.las"), f"sum{i}")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def reader():
        try:
            for _ in range(20):
                rows = st.table("chunks").search().limit(3).to_list()
                assert isinstance(rows, list)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert st.table("documents").count_rows() == 6


def test_ingest_report_shape(tmp_path):
    from doc_intel_analysts.evidence.ingest import run_ingest

    st = make_store(tmp_path)
    entries = [
        {"key": "t/w/a.las", "asset_team": "t"},
        {"key": "t/w/b.xlsx", "asset_team": "t"},
        {"key": "t/w/gone.las", "asset_team": "t"},
    ]

    def fetch(key):
        if "gone" in key:
            raise RuntimeError("404")
        return b"DEPT GR\n9800 45\n" * 50

    report = run_ingest(entries, st, st._config.parsed_root, fetch=fetch)
    assert report["complete"] == 1 and report["skipped"] == 1 and report["failed"] == 1
    assert report["failures"][0]["reason"].startswith("fetch failed")
    assert report["table_counts"]["ledger"] == 3
    # re-run: completed doc is unchanged, failed fetch retries
    report2 = run_ingest(entries, st, st._config.parsed_root, fetch=fetch)
    assert report2["unchanged"] == 1


def test_ingest_max_new_stops_early_and_resumes(tmp_path):
    from doc_intel_analysts.evidence.ingest import run_ingest

    st = make_store(tmp_path)
    entries = [
        {"key": f"t/w/doc{i}.las", "asset_team": "t"} for i in range(3)
    ]

    def fetch(key):
        return b"DEPT GR\n9800 45\n" * 50

    report = run_ingest(entries, st, st._config.parsed_root, fetch=fetch, max_new=2)
    assert report["stopped_early"] is True
    assert report["complete"] == 2
    assert "table_counts" not in report  # maintenance deferred in batch mode
    # next batch fast-forwards the done docs and finishes the pass
    report2 = run_ingest(entries, st, st._config.parsed_root, fetch=fetch, max_new=2)
    assert report2["stopped_early"] is False
    assert report2["unchanged"] == 2 and report2["complete"] == 1
    # batch mode defers maintenance even when the pass finishes the listing
    assert "table_counts" not in report2


def test_parse_failure_counts_failed_and_retries(tmp_path):
    from doc_intel_analysts.evidence.ingest import run_ingest

    st = make_store(tmp_path)
    entries = [{"key": "t/w/a.las", "asset_team": "t"}]
    payload = {"data": b""}  # empty text file — parse raises

    def fetch(key):
        return payload["data"]

    report = run_ingest(entries, st, st._config.parsed_root, fetch=fetch)
    assert report["failed"] == 1 and report["skipped"] == 0
    assert "parse failed" in report["failures"][0]["reason"]
    from doc_intel_analysts.evidence.parse import doc_id_for_key

    row = st.ledger_status(doc_id_for_key("t/w/a.las"))
    assert row["status"] == "failed" and row["checksum"] == ""
    # next pass retries the doc; good bytes now complete it
    payload["data"] = b"DEPT GR\n9800 45\n" * 50
    report2 = run_ingest(entries, st, st._config.parsed_root, fetch=fetch)
    assert report2["complete"] == 1 and report2["unchanged"] == 0


def test_max_new_counts_skips_toward_cap(tmp_path):
    from doc_intel_analysts.evidence.ingest import run_ingest

    st = make_store(tmp_path)
    entries = [
        {"key": f"t/w/sheet{i}.xlsx", "asset_team": "t"} for i in range(3)
    ]

    def fetch(key):  # gate skips never fetch
        raise AssertionError("format-gate skip must not fetch")

    report = run_ingest(entries, st, st._config.parsed_root, fetch=fetch, max_new=1)
    assert report["stopped_early"] is True
    assert report["skipped"] == 1 and report["complete"] == 0


def test_max_new_zero_processes_nothing(tmp_path):
    from doc_intel_analysts.evidence.ingest import run_ingest

    st = make_store(tmp_path)
    entries = [{"key": "t/w/a.las", "asset_team": "t"}]

    report = run_ingest(entries, st, st._config.parsed_root, fetch=None, max_new=0)
    assert report["stopped_early"] is True
    assert report["complete"] == 0 and st.table("ledger").count_rows() == 0


def test_crashed_first_ingest_reconciles_without_duplicates(tmp_path):
    from doc_intel_analysts.evidence import parse
    from doc_intel_analysts.evidence.ingest import run_ingest

    st = make_store(tmp_path)
    data = b"DEPT GR\n9800 45\n" * 50
    # simulate a crash between _insert_rows and _write_ledger: table rows
    # exist, ledger row does not
    doc = parse.parse_document("t/w/a.las", data, st._config.parsed_root, asset_team="t")
    st._insert_rows(doc)
    assert st.table("pages").count_rows() == 1
    assert st.ledger_status(doc.doc_id) is None

    entries = [{"key": "t/w/a.las", "asset_team": "t"}]
    report = run_ingest(entries, st, st._config.parsed_root, fetch=lambda key: data)
    assert report["reconciled"] == 1 and report["complete"] == 1
    # the orphaned rows were cleaned, not duplicated
    assert st.table("pages").count_rows() == 1
    assert st.table("documents").count_rows() == 1


def test_optimize_accepts_table_subset(tmp_path):
    from doc_intel_analysts.evidence.ingest import run_ingest

    st = make_store(tmp_path)
    entries = [{"key": "t/w/a.las", "asset_team": "t"}]

    def fetch(key):
        return b"DEPT GR\n9800 45\n" * 50

    run_ingest(entries, st, st._config.parsed_root, fetch=fetch)
    st.optimize(["documents", "ledger"])  # light maintenance path
    assert st.table("documents").count_rows() == 1


def test_terminal_image_skip_settles_with_checksum(tmp_path):
    """U2/KTD2 end-to-end: unidentifiable-bytes is one of the two
    deterministic image-failure classes commit 5b513c9 made terminal in
    parse_document. run_ingest's non-retriable branch must route it through
    store.record_skip with the entry's etag checksum, landing a "skipped"
    ledger row — never "failed" — with that checksum attached."""
    from doc_intel_analysts.evidence.ingest import run_ingest

    st = make_store(tmp_path)
    entries = [{"key": "t/w/broken.png", "asset_team": "t", "etag": "e1"}]

    def fetch(key):
        return b"not an image at all"

    report = run_ingest(entries, st, st._config.parsed_root, fetch=fetch)
    assert report["skipped"] == 1 and report["failed"] == 0
    row = st.ledger_status(parse.doc_id_for_key("t/w/broken.png"))
    assert row["status"] == "skipped"
    assert row["checksum"] == "etag:e1"


def test_settled_etag_skip_is_not_refetched(tmp_path):
    """No re-fetch: once a terminal skip has settled under an etag
    checksum, a second pass over the same (key, etag) must short-circuit at
    the pre-fetch etag gate in run_ingest — needs_ingest treats "skipped +
    matching checksum" as settled, so the fetch stub is never called again."""
    from doc_intel_analysts.evidence.ingest import run_ingest

    st = make_store(tmp_path)
    entries = [{"key": "t/w/broken.png", "asset_team": "t", "etag": "e1"}]
    calls = []

    def fetch(key):
        calls.append(key)
        return b"not an image at all"

    run_ingest(entries, st, st._config.parsed_root, fetch=fetch)
    assert calls == ["t/w/broken.png"]  # sanity: first pass did fetch once

    report2 = run_ingest(entries, st, st._config.parsed_root, fetch=fetch)
    assert report2["unchanged"] == 1
    assert calls == ["t/w/broken.png"], "second pass must not re-fetch settled bytes"


def test_etag_change_reopens_terminal_skip(tmp_path):
    """Reopen on change: a new etag on the same key busts the settled
    checksum, so run_ingest re-fetches and re-parses even though the
    document was terminally skipped before. The new (still-unidentifiable)
    bytes skip again, but the ledger checksum moves to the new etag —
    proving the reopen is real, not a no-op re-skip of stale state."""
    from doc_intel_analysts.evidence.ingest import run_ingest

    st = make_store(tmp_path)
    key = "t/w/broken.png"
    calls = []

    def fetch_v1(_key):
        calls.append(_key)
        return b"not an image at all"

    run_ingest(
        [{"key": key, "asset_team": "t", "etag": "e1"}],
        st,
        st._config.parsed_root,
        fetch=fetch_v1,
    )
    assert len(calls) == 1

    def fetch_v2(_key):
        calls.append(_key)
        return b"still not identifiable, but entirely different bytes"

    report = run_ingest(
        [{"key": key, "asset_team": "t", "etag": "e2"}],
        st,
        st._config.parsed_root,
        fetch=fetch_v2,
    )
    assert len(calls) == 2, "changed etag must trigger a re-fetch"
    assert report["skipped"] == 1
    row = st.ledger_status(parse.doc_id_for_key(key))
    assert row["checksum"] == "etag:e2"


def _seed_status_corpus(tmp_path):
    """Four ledger states: complete, gate-skip w/o etag (empty checksum),
    gate-skip w/ etag (terminal), parse failure."""
    from doc_intel_analysts.evidence.ingest import run_ingest
    from doc_intel_analysts.evidence.retrieval import EvidenceRetriever

    st = make_store(tmp_path)
    entries = [
        {"key": "TEAM A/w/good.las", "asset_team": "TEAM A"},
        {"key": "TEAM A/w/plain.xlsx", "asset_team": "TEAM A"},
        {"key": "TEAM B/w/tagged.xlsx", "asset_team": "TEAM B", "etag": "e1"},
        {"key": "TEAM A/w/broken.las", "asset_team": "TEAM A"},
    ]
    payloads = {
        "TEAM A/w/good.las": b"DEPT GR\n9800 45\n" * 50,
        "TEAM A/w/broken.las": b"",  # empty text file - parse raises
    }
    run_ingest(entries, st, st._config.parsed_root, fetch=lambda k: payloads[k])
    return st, EvidenceRetriever(st, query_embedder=fake_text_embedder())


def test_document_status_classifies_and_mirrors_needs_ingest(tmp_path):
    st, retriever = _seed_status_corpus(tmp_path)
    result = retriever.document_status()

    assert result["summary"] == {"complete": 1, "skipped": 2, "failed": 1}
    assert result["total_matches"] == 4
    assert result["ledger_as_of"]
    by_key = {r["s3key"]: r for r in result["matches"]}
    assert all("checksum" not in r for r in result["matches"])
    assert by_key["TEAM A/w/good.las"]["status"] == "complete"
    assert by_key["TEAM A/w/good.las"]["will_retry"] is False
    assert by_key["TEAM A/w/broken.las"]["status"] == "failed"
    assert by_key["TEAM A/w/broken.las"]["will_retry"] is True
    # gate skip without etag: verdict recorded without byte identity - re-runs
    assert by_key["TEAM A/w/plain.xlsx"]["status"] == "skipped"
    assert by_key["TEAM A/w/plain.xlsx"]["will_retry"] is True
    # gate skip with etag: terminal for those bytes
    assert by_key["TEAM B/w/tagged.xlsx"]["status"] == "skipped"
    assert by_key["TEAM B/w/tagged.xlsx"]["will_retry"] is False
    assert by_key["TEAM B/w/tagged.xlsx"]["reason"]
    # parity contract: will_retry mirrors needs_ingest for unchanged bytes
    for row in result["matches"]:
        stored = st.ledger_status(row["doc_id"])
        assert row["will_retry"] == st.needs_ingest(row["doc_id"], stored["checksum"])


def test_document_status_filters_limit_and_empty(tmp_path):
    st, retriever = _seed_status_corpus(tmp_path)

    skipped_only = retriever.document_status(status="skipped")
    assert skipped_only["summary"] == {"complete": 0, "skipped": 2, "failed": 0}

    frag = retriever.document_status(name_query="GOOD.las")
    assert frag["total_matches"] == 1

    team_b = retriever.document_status(asset_team="TEAM B")
    assert {r["s3key"] for r in team_b["matches"]} == {"TEAM B/w/tagged.xlsx"}

    lim = retriever.document_status(limit=2)
    assert len(lim["matches"]) == 2
    assert lim["total_matches"] == 4  # summary reflects the full matched set

    none = retriever.document_status(name_query="zzz-not-there")
    assert none["matches"] == []
    assert none["total_matches"] == 0
    assert none["summary"] == {"complete": 0, "skipped": 0, "failed": 0}
    assert none["ledger_as_of"]  # watermark present even on empty results


def test_document_status_treats_fragment_literally(tmp_path):
    """LIKE wildcards in filenames/queries must not act as wildcards (review #4)."""
    from doc_intel_analysts.evidence.ingest import run_ingest
    from doc_intel_analysts.evidence.retrieval import EvidenceRetriever

    st = make_store(tmp_path)
    entries = [
        {"key": "T/w/a_b.las", "asset_team": "T"},
        {"key": "T/w/axb.las", "asset_team": "T"},
    ]
    payload = b"DEPT GR\n9800 45\n" * 50
    run_ingest(entries, st, st._config.parsed_root, fetch=lambda k: payload)
    retriever = EvidenceRetriever(st, query_embedder=fake_text_embedder())

    literal = retriever.document_status(name_query="a_b")
    assert {r["s3key"] for r in literal["matches"]} == {"T/w/a_b.las"}
    assert literal["total_matches"] == 1  # '_' must not match the 'x' in axb

    percent = retriever.document_status(name_query="%")
    assert percent["total_matches"] == 0  # literal percent matches nothing


def test_document_status_asset_team_case_insensitive(tmp_path):
    """Wrong-cased team must not fake absence (review #5)."""
    _, retriever = _seed_status_corpus(tmp_path)
    lowered = retriever.document_status(asset_team="team b/")
    assert {r["s3key"] for r in lowered["matches"]} == {"TEAM B/w/tagged.xlsx"}
