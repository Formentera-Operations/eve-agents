"""U5 endpoint tests: pass-through, 404s, and the service-side vision gate."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from doc_intel_analysts.evidence import api
from doc_intel_analysts.evidence.retrieval import PageHit


class FakeRetriever:
    def __init__(self):
        self.calls = []
        self.pages = {
            "doc-1:p1": {
                "page_id": "doc-1:p1",
                "doc_id": "doc-1",
                "page_num": 1,
                "s3key": "TEAM/WELL/doc.pdf",
                "asset_team": "TEAM",
                "text": "page text",
                "has_screenshot": True,
                "screenshot": b"\xff\xd8jpeg",
            }
        }

    def search(self, query, *, mode, limit, asset_team):
        self.calls.append(("search", query, mode, limit, asset_team))
        if mode == "bogus":
            raise ValueError(f"unknown mode {mode!r}")
        return [
            PageHit(
                page_id="doc-1:p1",
                doc_id="doc-1",
                page_num=1,
                s3key="TEAM/WELL/doc.pdf",
                asset_team="TEAM",
                score=0.04,
                signals={"chunks": 1},
                snippet="page text",
            )
        ]

    def grep(self, pattern, *, regex, limit, asset_team):
        self.calls.append(("grep", pattern, regex, limit, asset_team))
        return []

    def find_documents(self, name_query, *, asset_team, format_gate, limit):
        self.calls.append(("find", name_query, asset_team, format_gate, limit))
        return []

    def get_page(self, page_id, *, include_screenshot=False):
        page = self.pages.get(page_id)
        if page is None:
            return None
        page = dict(page)
        if not include_screenshot:
            page.pop("screenshot")
        return page

    def get_document_pages(self, doc_id):
        return [p for p in self.pages.values() if p["doc_id"] == doc_id]


@pytest.fixture
def client(monkeypatch):
    fake = FakeRetriever()
    monkeypatch.setattr(api, "get_retriever", lambda: fake)
    monkeypatch.setattr(
        api, "_vision_finding", lambda question, shot: f"vision({question})"
    )
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app), fake


def test_search_passes_filters_through(client):
    http, fake = client
    res = http.post(
        "/evidence/search",
        json={"query": "stuck pipe", "mode": "chunks", "limit": 7, "asset_team": "TEAM"},
    )
    assert res.status_code == 200
    assert fake.calls == [("search", "stuck pipe", "chunks", 7, "TEAM")]
    assert res.json()["hits"][0]["page_id"] == "doc-1:p1"


def test_unknown_mode_is_422(client):
    http, _ = client
    res = http.post("/evidence/search", json={"query": "q", "mode": "bogus"})
    assert res.status_code == 422


def test_read_unknown_page_404s(client):
    http, _ = client
    res = http.post("/evidence/read", json={"page_id": "nope:p9"})
    assert res.status_code == 404


def test_read_without_question_returns_text_only(client):
    http, _ = client
    res = http.post("/evidence/read", json={"page_id": "doc-1:p1"})
    body = res.json()
    assert body["text"] == "page text"
    assert "vision_finding" not in body
    assert "screenshot" not in body


def test_read_with_question_returns_vision_finding_and_citation(client):
    http, _ = client
    res = http.post(
        "/evidence/read",
        json={"page_id": "doc-1:p1", "question": "what is on the plot?"},
    )
    body = res.json()
    assert body["vision_finding"] == "vision(what is on the plot?)"
    assert body["vision_citation"] == {"s3key": "TEAM/WELL/doc.pdf", "page": 1}
    assert "screenshot" not in body, "bytes never transit the seam"


def test_read_requires_an_identity(client):
    http, _ = client
    assert http.post("/evidence/read", json={}).status_code == 422


def test_read_whole_document(client):
    http, _ = client
    res = http.post("/evidence/read", json={"doc_id": "doc-1"})
    body = res.json()
    assert body["doc_id"] == "doc-1" and len(body["pages"]) == 1
