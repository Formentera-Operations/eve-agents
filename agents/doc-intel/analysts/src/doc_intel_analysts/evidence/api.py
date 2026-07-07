"""Evidence store endpoints on the analysts service (U5, KTD7).

The four eve tools talk to these, never to LanceDB directly. Every result
carries page-level identity (`page_id`) and the corpus `s3key` so the eve
side can verify and cite real pages.

R7 answer-time vision is SERVICE-SIDE (KTD10 spike, see
decisions/2026-07-06-evidence-read-vision-mechanism.md): eve 0.19 cannot
put images in front of its model, so `/evidence/read` accepts an optional
`question` — this service sends the stored page screenshot to gateway
vision itself and returns a text finding with the page citation. Screenshot
bytes never transit the seam.
"""

import base64
import os
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/evidence")

DEFAULT_VISION_MODEL = "anthropic/claude-haiku-4.5"
VISION_PROMPT = (
    "You are reading one page of an oil & gas well file. Answer the question "
    "strictly from what is visible on this page image. If the page does not "
    "contain the answer, say so plainly. Quote values exactly as printed."
)


@lru_cache(maxsize=1)
def get_retriever():
    from doc_intel_analysts.evidence.config import load_config
    from doc_intel_analysts.evidence.retrieval import EvidenceRetriever
    from doc_intel_analysts.evidence.store import EvidenceStore

    return EvidenceRetriever(EvidenceStore(load_config()))


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    mode: str = Field(default="hybrid_bundle")
    limit: int = Field(default=5, ge=1, le=25)
    asset_team: str | None = None


class GrepRequest(BaseModel):
    pattern: str = Field(min_length=1)
    regex: bool = False
    limit: int = Field(default=20, ge=1, le=100)
    asset_team: str | None = None


class FindRequest(BaseModel):
    name_query: str = ""
    asset_team: str | None = None
    format_gate: str | None = None
    limit: int = Field(default=25, ge=1, le=100)


class ReadRequest(BaseModel):
    page_id: str | None = None
    doc_id: str | None = None
    question: str | None = Field(
        default=None,
        description="When set, the page screenshot is read through gateway "
        "vision and a text finding is returned (R7).",
    )


@router.get("/health")
def health() -> dict[str, Any]:
    try:
        retriever = get_retriever()
        return {"ok": True, "table_counts": retriever._store.counts()}
    except Exception as err:  # noqa: BLE001
        return {"ok": False, "error": str(err)[:200]}


@router.post("/search")
def search(req: SearchRequest) -> dict[str, Any]:
    try:
        hits = get_retriever().search(
            req.query, mode=req.mode, limit=req.limit, asset_team=req.asset_team
        )
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    return {"hits": [h.to_dict() for h in hits], "mode": req.mode}


@router.post("/grep")
def grep(req: GrepRequest) -> dict[str, Any]:
    try:
        matches = get_retriever().grep(
            req.pattern, regex=req.regex, limit=req.limit, asset_team=req.asset_team
        )
    except Exception as err:  # noqa: BLE001 — bad regex etc.
        raise HTTPException(status_code=422, detail=str(err)[:200]) from err
    return {"matches": matches}


@router.post("/find")
def find(req: FindRequest) -> dict[str, Any]:
    documents = get_retriever().find_documents(
        req.name_query,
        asset_team=req.asset_team,
        format_gate=req.format_gate,
        limit=req.limit,
    )
    return {"documents": documents}


@router.post("/read")
def read(req: ReadRequest) -> dict[str, Any]:
    if not req.page_id and not req.doc_id:
        raise HTTPException(status_code=422, detail="page_id or doc_id required")
    retriever = get_retriever()

    if req.doc_id and not req.page_id:
        pages = retriever.get_document_pages(req.doc_id)
        if not pages:
            raise HTTPException(status_code=404, detail=f"unknown doc_id {req.doc_id!r}")
        return {
            "doc_id": req.doc_id,
            "s3key": pages[0]["s3key"],
            "pages": [
                {"page_id": p["page_id"], "page_num": p["page_num"], "text": p["text"]}
                for p in sorted(pages, key=lambda p: p["page_num"])
            ],
        }

    needs_vision = bool(req.question)
    page = retriever.get_page(req.page_id, include_screenshot=needs_vision)
    if page is None:
        raise HTTPException(status_code=404, detail=f"unknown page_id {req.page_id!r}")
    response: dict[str, Any] = {
        "page_id": page["page_id"],
        "doc_id": page["doc_id"],
        "page_num": page["page_num"],
        "s3key": page["s3key"],
        "asset_team": page["asset_team"],
        "text": page["text"],
        "has_screenshot": page["has_screenshot"],
    }
    if needs_vision:
        screenshot = page.get("screenshot")
        if not screenshot:
            response["vision_finding"] = (
                "This page has no stored screenshot; only its text layer is available."
            )
        else:
            response["vision_finding"] = _vision_finding(req.question, screenshot)
        response["vision_citation"] = {
            "s3key": page["s3key"],
            "page": page["page_num"],
        }
    return response


def _vision_finding(question: str, screenshot_jpeg: bytes) -> str:
    """Send the page screenshot to gateway vision; return a text finding.

    Same gateway credential and endpoint as embeddings — the config guard
    already validated it. This is the only place page pixels meet a model.
    """
    from openai import OpenAI

    from doc_intel_analysts.evidence.config import load_config

    config = load_config()
    client = OpenAI(base_url=config.gateway_base_url, api_key=config.gateway_api_key)
    model = os.environ.get("EVIDENCE_VISION_MODEL", DEFAULT_VISION_MODEL)
    data_url = "data:image/jpeg;base64," + base64.b64encode(screenshot_jpeg).decode()
    completion = client.chat.completions.create(
        model=model,
        max_tokens=800,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"{VISION_PROMPT}\n\nQuestion: {question}"},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
    )
    return completion.choices[0].message.content or ""
