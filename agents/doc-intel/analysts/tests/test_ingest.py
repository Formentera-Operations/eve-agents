"""U3 contract tests: serialization branches, sampling, ledger vocabulary."""

from doc_intel_analysts.graph.ingest import sample_trial, serialize_view

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
