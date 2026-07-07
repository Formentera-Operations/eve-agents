"""U6 harness tests: known hits/misses produce known scores."""

from doc_intel_analysts.evidence.benchmark import run_benchmark, score_question


def hit(s3key, page, signals):
    return {
        "page_id": f"doc:{page}",
        "s3key": s3key,
        "page_num": page,
        "signals": signals,
    }


QUESTIONS = [
    {
        "id": "Q1",
        "question": "text question, hit",
        "modality": "text",
        "expected_pages": [{"s3key": "a.pdf", "page": 3}],
    },
    {
        "id": "Q2",
        "question": "figure question, hit but only via text signal",
        "modality": "figure",
        "expected_pages": [{"s3key": "b.pdf", "page": 1}],
    },
    {
        "id": "Q3",
        "question": "text question, miss",
        "modality": "text",
        "expected_pages": [{"s3key": "c.pdf", "page": 9}],
    },
    {
        "id": "Q4",
        "question": "figure question, image hit",
        "modality": "figure",
        "expected_pages": [{"s3key": "d.pdf", "page": 2}, {"s3key": "d.pdf", "page": 5}],
    },
]

RESULTS = {
    "text question, hit": [hit("a.pdf", 3, {"chunks": 1})],
    "figure question, hit but only via text signal": [hit("b.pdf", 1, {"chunks": 2})],
    "text question, miss": [hit("x.pdf", 1, {"chunks": 1})],
    "figure question, image hit": [
        hit("d.pdf", 2, {"images": 1}),
        hit("y.pdf", 7, {"chunks": 3}),
    ],
}


def test_known_fixture_produces_known_scores():
    report = run_benchmark(QUESTIONS, lambda q: RESULTS[q])
    assert report["n"] == 4
    # Q1, Q2, Q4 have any-page hits; Q3 misses -> 3/4
    assert report["any_page_hit@5"] == 0.75
    # coverage: Q1=1, Q2=1, Q3=0, Q4=0.5 -> 2.5/4
    assert report["page_coverage@5"] == 0.625
    # modality: Q1 yes (text via chunks), Q2 NO (figure needs image signal),
    # Q3 no, Q4 yes -> 2/4
    assert report["modality_hit@5"] == 0.5


def test_figure_question_requires_image_signal():
    scored = score_question(QUESTIONS[1], RESULTS["figure question, hit but only via text signal"])
    assert scored["any_page_hit"] is True
    assert scored["modality_hit"] is False, "R8: figure evidence must be image-reachable"


def test_by_modality_breakdown():
    report = run_benchmark(QUESTIONS, lambda q: RESULTS[q])
    assert report["by_modality"]["figure"]["n"] == 2
    assert report["by_modality"]["figure"]["modality_hit@5"] == 0.5
    assert report["by_modality"]["text"]["any_page_hit@5"] == 0.5


def test_only_top5_counts():
    question = {
        "id": "Q5",
        "question": "q",
        "modality": "text",
        "expected_pages": [{"s3key": "z.pdf", "page": 1}],
    }
    hits = [hit("n.pdf", i, {"chunks": i}) for i in range(1, 6)] + [
        hit("z.pdf", 1, {"chunks": 6})
    ]
    scored = score_question(question, hits)
    assert scored["any_page_hit"] is False, "rank 6 is outside @5"
