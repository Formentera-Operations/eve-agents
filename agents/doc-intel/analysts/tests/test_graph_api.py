"""U4 contract tests: source-key recovery from arbitrary cognee payloads."""

from doc_intel_analysts.graph.api import extract_source_keys


def test_extracts_keys_with_underscores_commas_and_spaces():
    payload = {
        "results": [
            {"node_set": ["s3key:FP GRIFFIN/GOODNIGHT, SELMA 2H/Financial/AFE/a__b.pdf"]},
            {"nested": {"tags": ("s3key:A/B__C", "unrelated")}},
        ]
    }
    keys = extract_source_keys(payload)
    assert keys == [
        "FP GRIFFIN/GOODNIGHT, SELMA 2H/Financial/AFE/a__b.pdf",
        "A/B__C",
    ]


def test_dedupes_and_preserves_order():
    payload = ["s3key:one", {"a": "s3key:two"}, ["s3key:one"], "s3key:three"]
    assert extract_source_keys(payload) == ["one", "two", "three"]


def test_ignores_non_tag_strings_and_empty_tags():
    assert extract_source_keys(["plain", "s3key:", {"x": 42}, None]) == []


def test_extracts_evidence_doc_ids_with_prefix_param():
    from doc_intel_analysts.graph.api import DOC_TAG_PREFIX

    payload = ["s3key:TEAM/W/a.pdf", "doc_id:2026-02-08-summary-34499867-7fd980bf", "doc_id:"]
    assert extract_source_keys(payload) == ["TEAM/W/a.pdf"]
    assert extract_source_keys(payload, prefix=DOC_TAG_PREFIX) == [
        "2026-02-08-summary-34499867-7fd980bf"
    ]


def test_extracts_keys_from_pydantic_model_results():
    from pydantic import BaseModel

    class Chunk(BaseModel):
        text: str
        belongs_to_set: list[str]

    payload = [Chunk(text="...", belongs_to_set=["s3key:TEAM/WELL/doc.pdf"])]
    assert extract_source_keys(payload) == ["TEAM/WELL/doc.pdf"]
