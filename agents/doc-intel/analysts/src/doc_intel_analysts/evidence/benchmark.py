"""Retrieval-layer benchmark harness (U6, KTD9, R8).

Scores a page-labeled, modality-tagged question set against the evidence
store with the reference implementation's metrics:

- ``any_page_hit@5``  — at least one expected page in the top 5.
- ``page_coverage@5`` — fraction of expected pages found in the top 5.
- ``modality_hit@5``  — an expected page in the top 5 that surfaced through
  a signal appropriate to the question's modality (figure questions must be
  reachable through image/asset signals or answer-time vision would never
  see the page for the right reason; text and text-native questions count
  any text signal).

The answer layer is NOT here: the 25-question benchmark stays the manual,
spot-verified procedure in `benchmark/README.md` (an automated runner is
deferred follow-up work).

Run from the analysts directory:

    uv run python -m doc_intel_analysts.evidence.benchmark \
        --questions ../../../benchmark/evidence-questions.json
"""

import argparse
import json
from pathlib import Path

TOP_K = 5

MODALITY_SIGNALS = {
    "text": {"chunks", "pages", "fts"},
    "text_native": {"chunks", "pages", "fts"},
    "table": {"chunks", "pages", "fts", "images", "assets"},
    "figure": {"images", "assets"},
}


def score_question(question: dict, hits: list[dict]) -> dict:
    """Score one question against its top-K hits.

    `hits` are PageHit dicts (page-ranked). Expected pages are
    {"s3key": ..., "page": int}; matching is exact on both.
    """
    expected = {(e["s3key"], e["page"]) for e in question["expected_pages"]}
    top = hits[:TOP_K]
    found = {
        (h["s3key"], h["page_num"])
        for h in top
        if (h["s3key"], h["page_num"]) in expected
    }
    modality = question["modality"]
    allowed = MODALITY_SIGNALS[modality]
    modality_hit = any(
        (h["s3key"], h["page_num"]) in expected
        and (set(h.get("signals", {})) & allowed)
        for h in top
    )
    return {
        "id": question["id"],
        "modality": modality,
        "any_page_hit": bool(found),
        "page_coverage": len(found) / len(expected) if expected else 0.0,
        "modality_hit": modality_hit,
        "top_pages": [
            {"page_id": h["page_id"], "signals": h.get("signals", {})} for h in top
        ],
    }


def run_benchmark(questions: list[dict], search_fn) -> dict:
    """`search_fn(question_text) -> list[PageHit dict]` (page-ranked).

    Injectable so the harness itself is testable against known fixtures.
    """
    per_question = []
    for question in questions:
        hits = search_fn(question["question"])
        per_question.append(score_question(question, hits))

    def rate(rows, key):
        return round(sum(r[key] for r in rows) / len(rows), 3) if rows else 0.0

    by_modality = {}
    for modality in sorted({q["modality"] for q in questions}):
        rows = [r for r in per_question if r["modality"] == modality]
        by_modality[modality] = {
            "n": len(rows),
            "any_page_hit@5": rate(rows, "any_page_hit"),
            "page_coverage@5": rate(rows, "page_coverage"),
            "modality_hit@5": rate(rows, "modality_hit"),
        }
    return {
        "n": len(per_question),
        "any_page_hit@5": rate(per_question, "any_page_hit"),
        "page_coverage@5": rate(per_question, "page_coverage"),
        "modality_hit@5": rate(per_question, "modality_hit"),
        "by_modality": by_modality,
        "per_question": per_question,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evidence retrieval benchmark")
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--asset-team", default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    from doc_intel_analysts.evidence.config import load_config
    from doc_intel_analysts.evidence.retrieval import EvidenceRetriever
    from doc_intel_analysts.evidence.store import EvidenceStore

    retriever = EvidenceRetriever(EvidenceStore(load_config()))

    def search_fn(text: str) -> list[dict]:
        return [
            h.to_dict()
            for h in retriever.search(text, limit=TOP_K, asset_team=args.asset_team)
        ]

    questions = json.loads(args.questions.read_text())["questions"]
    report = run_benchmark(questions, search_fn)
    output = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(output)
    print(output)


if __name__ == "__main__":
    main()
