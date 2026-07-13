"""Latency-bench runner tests: all 10 op rows against a temp store, a
test-lowered cap that records the timeout sentinel instead of hanging, error
rows that keep the run alive, and capped fixture sampling that fails loud."""

import io
import json
import subprocess
import sys
import time

import pytest

from doc_intel_analysts.evidence import latency_bench, parse, store
from doc_intel_analysts.evidence.config import EvidenceConfig

DIMS = 8

EXPECTED_OPS = [
    "open+count(4 tables)",
    "vector search (chunks, hybrid leg)",
    "fts search (chunks)",
    "grep exact 'S733H' (pages scan)",
    "grep filtered '9,020' (Westlake)",
    "find_documents 'surveys'",
    "document_status '.xlsx' skipped",
    "get_page (text)",
    "get_page (+screenshot blob)",
    "get_document_pages",
]


def make_config(tmp_path) -> EvidenceConfig:
    return EvidenceConfig(
        gateway_base_url="https://ai-gateway.vercel.sh/v1",
        gateway_api_key="test-key",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=DIMS,
        clip_model="ViT-B-32-quickgelu",
        clip_pretrained="openai",
        store_root=tmp_path / ".evidence",
        lance_root=tmp_path / ".evidence" / "lance",
        parsed_root=tmp_path / ".evidence" / "parsed",
    )


def keyword_vector(text: str) -> list[float]:
    keywords = ["stuck", "pipe", "casing", "cement", "survey", "frac", "gamma", "cost"]
    return [1.0 if k in text.lower() else 0.01 for k in keywords]


class FakeClip:
    def __call__(self, images):
        vectors = []
        for data in images:
            from PIL import Image

            img = Image.open(io.BytesIO(data)).convert("RGB")
            r, g, b = img.resize((1, 1)).getpixel((0, 0))
            vec = [0.0] * store.CLIP_DIMENSIONS
            vec[0 if r > g else 1] = 1.0
            vectors.append(vec)
        return vectors

    def embed_text(self, query):
        vec = [0.0] * store.CLIP_DIMENSIONS
        vec[0 if "red" in query else 1] = 1.0
        return vec


def colored_jpeg(rgb) -> bytes:
    from PIL import Image

    img = Image.new("RGB", (64, 48), rgb)
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def lance_root(tmp_path):
    cfg = make_config(tmp_path)
    cfg.lance_root.mkdir(parents=True, exist_ok=True)
    cfg.parsed_root.mkdir(parents=True, exist_ok=True)
    st = store.EvidenceStore(
        cfg,
        text_embedder=lambda texts: [keyword_vector(t) for t in texts],
        image_embedder=FakeClip(),
    )
    docs = [
        ("TEAM A/WELL 1/report.txt", "Stuck pipe incident at 9800 ft during trip out. " * 30),
        ("TEAM A/WELL 1/cement.txt", "Cement bond evaluation and casing integrity. " * 30),
        ("TEAM B/WELL 2/survey.txt", "Directional survey gamma readings for well S733H. " * 30),
    ]
    for key, text in docs:
        team = key.split("/")[0]
        doc = parse.parse_document(key, text.encode(), None, asset_team=team)
        st.upsert_document(doc, f"sum-{key}")
    red = parse.parse_document(
        "TEAM B/WELL 2/redplat.jpg", colored_jpeg((220, 20, 20)), None, asset_team="TEAM B"
    )
    st.upsert_document(red, "sum-red")
    st.build_indexes()
    return cfg.lance_root


def test_timed_returns_elapsed_or_none_on_cap():
    assert isinstance(latency_bench.timed(lambda: 1, cap=5.0), float)
    assert latency_bench.timed(lambda: time.sleep(0.5), cap=0.05) is None


def test_all_ten_ops_produce_numeric_rows(lance_root):
    report = latency_bench.run_latency_bench([str(lance_root)], warm=1)
    assert report["fixtures"]["page_id"] and report["fixtures"]["doc_id"]
    rows = report["roots"][str(lance_root)]
    assert [row["op"] for row in rows] == EXPECTED_OPS
    for row in rows:
        assert isinstance(row["cold_s"], float), row
        assert isinstance(row["warm_median_s"], float), row
        assert row["within_60s_tool_budget"] is True, row


def test_op_exceeding_cap_records_sentinel_and_run_returns(lance_root, monkeypatch):
    def slow_grep(self, *args, **kwargs):
        time.sleep(0.5)
        return []

    monkeypatch.setattr(latency_bench.EvidenceRetriever, "grep", slow_grep)
    report = latency_bench.run_latency_bench([str(lance_root)], cap=0.05, warm=1)
    grep_rows = [
        row for row in report["roots"][str(lance_root)] if row["op"].startswith("grep")
    ]
    assert len(grep_rows) == 2
    for row in grep_rows:
        assert row["cold_s"] == ">0.05 TIMEOUT"
        assert row["warm_median_s"] == ">0.05 TIMEOUT"
        assert row["within_60s_tool_budget"] is False


def test_op_raising_error_records_sentinel_and_run_continues(lance_root, monkeypatch):
    def broken_grep(self, *args, **kwargs):
        raise ValueError("bad filter expression")

    monkeypatch.setattr(latency_bench.EvidenceRetriever, "grep", broken_grep)
    report = latency_bench.run_latency_bench([str(lance_root)], warm=1)
    rows = report["roots"][str(lance_root)]
    assert [row["op"] for row in rows] == EXPECTED_OPS
    for row in rows:
        if row["op"].startswith("grep"):
            assert row["cold_s"] == "ERROR: ValueError"
            assert row["warm_median_s"] == "ERROR: ValueError"
            assert row["within_60s_tool_budget"] is False
        else:
            assert isinstance(row["cold_s"], float), row
            assert isinstance(row["warm_median_s"], float), row


def test_fixture_sampling_exceeding_cap_fails_loud_naming_root(lance_root, monkeypatch):
    def slow_sample(store):
        time.sleep(0.5)

    monkeypatch.setattr(latency_bench, "sample_fixtures", slow_sample)
    with pytest.raises(latency_bench.FixtureSamplingError) as excinfo:
        latency_bench.run_latency_bench([str(lance_root)], cap=0.05, warm=1)
    assert "fixture sampling exceeded 0.05s" in str(excinfo.value)
    assert str(lance_root) in str(excinfo.value)


def test_cli_writes_json_and_exits_zero(lance_root, tmp_path):
    out = tmp_path / "latency.json"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "doc_intel_analysts.evidence.latency_bench",
            "--root",
            str(lance_root),
            "--out",
            str(out),
            "--warm",
            "1",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    report = json.loads(out.read_text())
    assert list(report["roots"]) == [str(lance_root)]
    assert len(report["roots"][str(lance_root)]) == 10


def test_cli_exits_nonzero_when_fixture_sampling_exceeds_cap(lance_root, tmp_path):
    out = tmp_path / "latency.json"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "doc_intel_analysts.evidence.latency_bench",
            "--root",
            str(lance_root),
            "--out",
            str(out),
            "--cap",
            "0.001",
            "--warm",
            "1",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode != 0
    assert "fixture sampling exceeded 0.001s" in proc.stderr
    assert str(lance_root) in proc.stderr
    assert not out.exists()
