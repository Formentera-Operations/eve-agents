"""Graph query endpoints on the analysts service (plan U4).

The eve tool talks to these, never to cognee directly. Source keys are
recovered from `s3key:` node_set tags (KTD3); provenance verification beyond
the document key happens on the eve side (KTD7).
"""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from . import runtime
from .config import DATASET_NAME

router = APIRouter(prefix="/graph")

TAG_PREFIX = "s3key:"
DOC_TAG_PREFIX = "doc_id:"


def extract_source_keys(payload: Any, prefix: str = TAG_PREFIX) -> list[str]:
    """Pull corpus keys out of any cognee result structure by walking it for
    node_set tags. Pure function; handles keys containing '__', commas, spaces.
    Evidence-ingested documents additionally carry doc_id: tags (pass
    DOC_TAG_PREFIX) so answers can be page-verified through read_evidence —
    their s3keys are not in the sample manifest that read_parsed_document
    accepts."""
    found: list[str] = []
    seen: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, str):
            if value.startswith(prefix):
                key = value[len(prefix):]
                if key and key not in seen:
                    seen.add(key)
                    found.append(key)
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, (list, tuple, set)):
            for v in value:
                walk(v)
        elif hasattr(value, "model_dump"):
            # cognee search results are pydantic models; tags live in
            # fields like belongs_to_set (verified live against 1.2.2).
            walk(value.model_dump())

    walk(payload)
    return found


class SearchRequest(BaseModel):
    question: str = Field(min_length=1)
    entity_scope: list[str] | None = Field(
        default=None, description="Optional corpus keys to scope the search to"
    )
    top_k: int = Field(default=10, ge=1, le=50)


class SearchResponse(BaseModel):
    answer: str
    evidence_doc_ids: list[str] = []
    sources: list[str]
    mode: str


@router.get("/health")
async def health() -> dict[str, Any]:
    try:
        cognee = runtime.get_cognee()
        datasets = await cognee.datasets.list_datasets()
        names = [getattr(d, "name", str(d)) for d in datasets]
        return {"ok": True, "datasets": names, "welldrive_present": DATASET_NAME in names}
    except Exception as err:
        return {"ok": False, "error": str(err)[:200]}


@router.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest) -> SearchResponse:
    cognee = runtime.get_cognee()
    from cognee.modules.search.types import SearchType

    kwargs: dict[str, Any] = {
        "query_text": req.question,
        "query_type": SearchType.GRAPH_COMPLETION,
        "datasets": DATASET_NAME,
        "top_k": req.top_k,
    }
    if req.entity_scope:
        kwargs["node_name"] = [f"{TAG_PREFIX}{k}" for k in req.entity_scope]

    results = await cognee.search(**kwargs)

    answer_parts: list[str] = []
    for item in results if isinstance(results, list) else [results]:
        if isinstance(item, str):
            answer_parts.append(item)
        elif isinstance(item, dict) and "text" in item:
            answer_parts.append(str(item["text"]))
        else:
            answer_parts.append(str(item))
    answer = "\n".join(answer_parts).strip()

    sources = extract_source_keys(results)
    doc_ids = extract_source_keys(results, prefix=DOC_TAG_PREFIX)
    if not sources:
        # Fallback (plan U4): raw chunk retrieval carries node_set context.
        try:
            chunks = await cognee.search(
                query_text=req.question,
                query_type=SearchType.CHUNKS,
                datasets=DATASET_NAME,
                top_k=req.top_k,
            )
            sources = extract_source_keys(chunks)
            doc_ids = extract_source_keys(chunks, prefix=DOC_TAG_PREFIX)
        except Exception:
            sources = []
            doc_ids = []

    return SearchResponse(answer=answer, sources=sources, evidence_doc_ids=doc_ids, mode="GRAPH_COMPLETION")
