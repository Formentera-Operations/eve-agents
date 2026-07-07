"""U4 contract tests: hybrid merge, prefilters, grep exactness, empty store."""

import io

import pytest

from doc_intel_analysts.evidence import parse, retrieval, store
from doc_intel_analysts.evidence.config import EvidenceConfig

DIMS = 8


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
    """Deterministic 'semantic' embedding: dimension i lights up when
    keyword i is present, so queries genuinely rank fixture docs."""
    keywords = ["stuck", "pipe", "casing", "cement", "survey", "frac", "gamma", "cost"]
    vec = [1.0 if k in text.lower() else 0.01 for k in keywords]
    return vec


class FakeClip:
    """Image embedder stub: red images and 'red' queries share a vector."""

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
def loaded(tmp_path):
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
    red = parse.parse_document("TEAM B/WELL 2/redplat.jpg", colored_jpeg((220, 20, 20)), None, asset_team="TEAM B")
    st.upsert_document(red, "sum-red")
    st.build_indexes()
    return retrieval.EvidenceRetriever(
        st, query_embedder=lambda texts: [keyword_vector(t) for t in texts]
    ), st


def test_hybrid_merges_signals_to_one_page(loaded):
    r, _ = loaded
    hits = r.search("stuck pipe at depth", limit=3)
    assert hits, "expected hits"
    top = hits[0]
    assert "report" in top.doc_id
    assert len({s for s in top.signals}) >= 2, f"multi-signal merge: {top.signals}"
    page_ids = [h.page_id for h in hits]
    assert len(page_ids) == len(set(page_ids)), "one result per page"


def test_prefilter_excludes_other_teams(loaded):
    r, _ = loaded
    hits = r.search("survey gamma readings", limit=5, asset_team="TEAM A")
    assert all(h.asset_team == "TEAM A" for h in hits)


def test_image_mode_finds_matching_screenshot(loaded):
    r, _ = loaded
    hits = r.search("red colored plat map", mode="images", limit=3)
    assert hits and "redplat" in hits[0].doc_id


def test_empty_store_returns_empty_not_error(tmp_path):
    cfg = make_config(tmp_path)
    cfg.lance_root.mkdir(parents=True, exist_ok=True)
    st = store.EvidenceStore(
        cfg,
        text_embedder=lambda texts: [keyword_vector(t) for t in texts],
        image_embedder=FakeClip(),
    )
    r = retrieval.EvidenceRetriever(
        st, query_embedder=lambda texts: [keyword_vector(t) for t in texts]
    )
    assert r.search("anything") == []
    assert r.grep("anything") == []
    assert r.find_documents("anything") == []
    assert r.get_page("nope:p1") is None


def test_grep_finds_tokenizer_hostile_code(loaded):
    r, _ = loaded
    results = r.grep("S733H")
    assert results and results[0]["match"] == "S733H"
    assert "S733H" in results[0]["context"]


def test_grep_regex_mode(loaded):
    r, _ = loaded
    results = r.grep(r"S\d{3}H", regex=True)
    assert results and results[0]["match"] == "S733H"


def test_unknown_mode_raises(loaded):
    r, _ = loaded
    with pytest.raises(ValueError, match="unknown mode"):
        r.search("x", mode="nope")


def test_find_documents_by_name_and_gate(loaded):
    r, _ = loaded
    docs = r.find_documents("cement")
    assert len(docs) == 1 and "cement" in docs[0]["s3key"]
    images = r.find_documents(format_gate="image")
    assert len(images) == 1 and images[0]["format_gate"] == "image"


def test_get_page_screenshot_gated(loaded):
    r, st = loaded
    pid = st.table("pages").search().where("has_screenshot = true").select(["page_id"]).to_list()[0]["page_id"]
    without = r.get_page(pid)
    assert "screenshot" not in without
    with_shot = r.get_page(pid, include_screenshot=True)
    assert with_shot["screenshot"][:2] == b"\xff\xd8"
