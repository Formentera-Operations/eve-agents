"""FastAPI seam: the eve agent's delegate_analysis tool POSTs here.

Contract (see decisions/2026-07-05-doc-intel-seam.md):
POST /analyze {question, documents: [{key, entry_type, parsed_ref}]}
  -> {answer, citations: [{key, page}], analyst_notes}
Document bodies never transit the seam; this service reads parsed content
from the derived bucket and seeds it into the deep agent's virtual files.
"""

import json
import logging
import os
import secrets
import sys

from fastapi import FastAPI
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .agent import build_agent
from .corpus import file_data, document_as_files, fetch_document

logging.basicConfig(stream=sys.stdout, format='{"level":"%(levelname)s","msg":%(message)r}')
log = logging.getLogger("doc-intel-analysts")
log.setLevel(logging.INFO)


def _auth_required() -> bool:
    """Hosted-mode flag, read at call time: any non-empty value means auth is required."""
    return bool(os.environ.get("ANALYSTS_REQUIRE_AUTH"))


# Fail closed in hosted mode: refusing to start beats serving openly.
if _auth_required() and not os.environ.get("ANALYSTS_API_TOKEN"):
    raise RuntimeError(
        "ANALYSTS_REQUIRE_AUTH is set but ANALYSTS_API_TOKEN is missing or empty; refusing to start."
    )


class BearerAuthMiddleware:
    """Bearer-token gate for hosted mode.

    Pure ASGI middleware — not an app-level dependency — because FastAPI's
    auto-mounted /docs, /redoc and /openapi.json bypass app dependencies;
    middleware runs before routing and covers every route. Reads
    ANALYSTS_API_TOKEN at request time: unset with ANALYSTS_REQUIRE_AUTH also
    unset means auth is disabled (local dev unchanged); the flag set without a
    token 401s every non-/health request rather than serving open (defense in
    depth against env drift past the startup guard). /health stays open for
    liveness probes. The presented credential is never logged or echoed.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        expected = os.environ.get("ANALYSTS_API_TOKEN", "")
        allowed = (
            scope["path"] == "/health"
            or (not expected and not _auth_required())
            or (bool(expected) and _bearer_matches(scope, expected))
        )
        if allowed:
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            {"detail": "Not authenticated"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
        await response(scope, receive, send)


def _bearer_matches(scope: Scope, expected: str) -> bool:
    header = next(
        (value for name, value in scope["headers"] if name == b"authorization"), b""
    )
    scheme, _, credential = header.partition(b" ")
    if scheme.lower() != b"bearer":
        return False
    return secrets.compare_digest(credential.strip(), expected.encode("utf-8"))


app = FastAPI(title="doc-intel-analysts")
app.add_middleware(BearerAuthMiddleware)

from .graph.api import router as graph_router  # noqa: E402
from .evidence.api import router as evidence_router  # noqa: E402

app.include_router(graph_router)
app.include_router(evidence_router)
_agent = None


def get_agent():
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent


class DocumentRef(BaseModel):
    key: str
    entry_type: str = ""
    parsed_ref: str = ""


class AnalyzeRequest(BaseModel):
    question: str = Field(min_length=1)
    documents: list[DocumentRef] = Field(min_length=1, max_length=25)


class Citation(BaseModel):
    key: str
    page: int


class AnalyzeResponse(BaseModel):
    answer: str
    citations: list[Citation]
    analyst_notes: str = ""
    documents_seeded: int = 0
    documents_missing: list[str] = []


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    files: dict[str, dict[str, str]] = {}
    manifest_lines = []
    missing: list[str] = []

    for doc in req.documents:
        view = fetch_document(doc.key, doc.parsed_ref or None)
        if view is None or (not view["pages"] and not view.get("extraction")):
            missing.append(doc.key)
            continue
        files.update(document_as_files(doc.key, view))
        manifest_lines.append(
            f"- {doc.key} | entry_type: {doc.entry_type or 'unknown'} | "
            f"kind: {view['kind']} | pages: {view['page_count']}"
        )

    if not files:
        return AnalyzeResponse(
            answer="None of the referenced documents have readable parsed content.",
            citations=[],
            analyst_notes="No documents could be seeded.",
            documents_missing=missing,
        )

    files["/_manifest.md"] = file_data("# Seeded documents\n\n" + "\n".join(manifest_lines))
    log.info(f"analyze: {len(manifest_lines)} docs seeded, {len(missing)} missing")

    result = await get_agent().ainvoke(
        {"messages": [{"role": "user", "content": req.question}], "files": files}
    )
    final = result["messages"][-1].content
    text = final if isinstance(final, str) else json.dumps(final)

    answer, citations, notes = _parse_final(text)
    return AnalyzeResponse(
        answer=answer,
        citations=citations,
        analyst_notes=notes,
        documents_seeded=len(manifest_lines),
        documents_missing=missing,
    )


def _parse_final(text: str) -> tuple[str, list[Citation], str]:
    """Parse the orchestrator's JSON final message, tolerating fenced output."""
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        candidate = candidate.partition("\n")[2] if not candidate.startswith("{") else candidate
    start, end = candidate.find("{"), candidate.rfind("}")
    if start >= 0 and end > start:
        try:
            payload = json.loads(candidate[start : end + 1])
            citations = [
                Citation(key=c["key"], page=int(c["page"]))
                for c in payload.get("citations", [])
                if isinstance(c, dict) and "key" in c and "page" in c
            ]
            return str(payload.get("answer", "")), citations, str(payload.get("analyst_notes", ""))
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    return text, [], "Orchestrator returned non-JSON output; citations unavailable."
