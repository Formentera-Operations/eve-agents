"""U3 contract tests: serialization branches, sampling, ledger vocabulary."""

from doc_intel_analysts.graph.ingest import (
    sample_trial,
    serialize_evidence_pages,
    serialize_view,
)

MD_VIEW = {
    "kind": "markdown",
    "pages": [{"page": 1, "markdown": "Alpha"}, {"page": 3, "markdown": "Beta"}],
    "page_count": 3,
}
EX_VIEW = {
    "kind": "extraction",
    "pages": [],
    "extraction": {"fields": {"afe_number": "52955", "total": 6000}, "field_pages": {"afe_number": [4]}},
    "page_count": 4,
}


def test_markdown_serialization_preserves_page_markers():
    text = serialize_view("T/W/a.pdf", MD_VIEW)
    assert "<!-- source: T/W/a.pdf | page: 1 -->" in text
    assert "<!-- source: T/W/a.pdf | page: 3 -->" in text
    assert "Alpha" in text and "Beta" in text


def test_extraction_serialization_is_non_empty_with_fields():
    text = serialize_view("T/W/afe.pdf", EX_VIEW)
    assert len(text) > 50
    assert "52955" in text and "afe_number" in text
    assert "field_page_citations" in text


def test_sampler_spans_teams_and_is_deterministic():
    rows = []
    for team in ("A TEAM", "B TEAM", "C TEAM"):
        for tier in ("pilot-tierA", "pilot-tierB"):
            for i in range(10):
                rows.append({"key": f"{team}/{tier}/doc{i:02d}.pdf", "asset_team": team, "parse_source": tier})
    picked = sample_trial(rows, 12)
    assert len(picked) == 12
    teams = {r["asset_team"] for r in picked}
    tiers = {r["parse_source"] for r in picked}
    assert teams == {"A TEAM", "B TEAM", "C TEAM"}
    assert tiers == {"pilot-tierA", "pilot-tierB"}
    assert picked == sample_trial(list(rows), 12)


def test_sampler_handles_small_pools():
    rows = [{"key": "A/x.pdf", "asset_team": "A", "parse_source": "pilot-tierA"}]
    assert sample_trial(rows, 20) == rows


def test_evidence_pages_serialize_like_parsed_views():
    # Same <!-- source | page --> shape as serialize_view, ordered by page,
    # image-only (empty-text) pages skipped.
    pages = [
        {"page_num": 3, "text": "Beta"},
        {"page_num": 1, "text": "Alpha"},
        {"page_num": 2, "text": "   "},
    ]
    text = serialize_evidence_pages("T/W/a.pdf", pages)
    assert text.index("page: 1") < text.index("page: 3")
    assert "<!-- source: T/W/a.pdf | page: 1 -->" in text
    assert "page: 2" not in text
    assert "Alpha" in text and "Beta" in text


def test_evidence_serialization_of_imageonly_doc_is_empty():
    assert serialize_evidence_pages("T/W/scan.tif", [{"page_num": 1, "text": ""}]) == ""


def test_sampler_buckets_by_custom_columns():
    rows = []
    for well in ("S617HF", "S513HF"):
        for cat in ("Completions/Frac", "Drilling/Daily Reports"):
            for i in range(5):
                rows.append({"key": f"W/{well}/{cat}/d{i}.pdf", "well": well, "category": cat})
    picked = sample_trial(rows, 8, bucket_cols=("well", "category"))
    assert len(picked) == 8
    assert {r["well"] for r in picked} == {"S617HF", "S513HF"}
    assert {r["category"] for r in picked} == {"Completions/Frac", "Drilling/Daily Reports"}
    assert picked == sample_trial(list(rows), 8, bucket_cols=("well", "category"))


def test_ontology_path_resolves_to_repo_root():
    from pathlib import Path

    import doc_intel_analysts.graph.ingest as ingest_mod

    repo_root = Path(ingest_mod.__file__).resolve().parents[6]
    assert (repo_root / "references" / "ontology" / "welldrive.owl").exists(), (
        "parents[6] from ingest.py must be the repo root holding the ontology"
    )


def test_resume_ignores_ledgers_without_local_store(monkeypatch, tmp_path):
    from doc_intel_analysts.graph import config, ingest

    monkeypatch.setattr(config, "SYSTEM_ROOT", tmp_path / "missing")
    assert ingest.already_ingested_keys() == set()
