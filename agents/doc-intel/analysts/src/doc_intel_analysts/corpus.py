"""Read parsed document content from the derived S3 bucket.

Mirrors the eve agent's lib/parsed.ts normalization: pilot tier-A extraction
runs and tier-B/C parse runs (plus doc-intel cache entries) become one view.
Document bodies never transit the eve↔analysts seam — this module is how the
analyst side reads them directly.
"""

import hashlib
import json
from typing import Any

import boto3

DERIVED_BUCKET = "formentera-welldrive-derived"
PARSE_CACHE_PREFIX = "runs/doc-intel/parsed/"

_s3 = boto3.client("s3")


def _get_json(bucket: str, key: str) -> dict[str, Any] | None:
    try:
        body = _s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        return json.loads(body)
    except Exception:
        return None


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Return {kind, pages: [{page, markdown}], extraction?, page_count}."""
    if isinstance(raw.get("pages"), list) and raw.get("kind") in ("markdown", "extraction"):
        return raw

    output = raw.get("output") or {}
    chunks = output.get("chunks")
    if isinstance(chunks, list):
        pages = []
        for i, chunk in enumerate(chunks):
            content = chunk.get("content")
            if not isinstance(content, str):
                continue
            page_range = (chunk.get("metadata") or {}).get("pageRange") or {}
            pages.append({"page": page_range.get("start", i + 1), "markdown": content})
        return {"kind": "markdown", "pages": pages, "page_count": len(pages)}

    value = output.get("value")
    if isinstance(value, dict):
        field_pages: dict[str, list[int]] = {}
        for name, meta in (output.get("metadata") or {}).items():
            cites = [
                c.get("page", {}).get("number")
                for c in (meta or {}).get("citations", [])
                if isinstance(c.get("page", {}).get("number"), int)
            ]
            if cites:
                field_pages[name] = cites
        all_pages = [p for pages in field_pages.values() for p in pages]
        return {
            "kind": "extraction",
            "pages": [],
            "extraction": {"fields": value, "field_pages": field_pages},
            "page_count": max(all_pages) if all_pages else 0,
        }

    return {"kind": "markdown", "pages": [], "page_count": 0}


def _cache_key(corpus_key: str) -> str:
    sha = hashlib.sha256(corpus_key.encode()).hexdigest()[:24]
    return f"{PARSE_CACHE_PREFIX}{sha}.json"


def fetch_document(corpus_key: str, parsed_ref: str | None) -> dict[str, Any] | None:
    """Fetch a document's parsed view via its parsed_ref or the shared cache."""
    raw = None
    if parsed_ref and parsed_ref.startswith("s3://"):
        bucket, _, key = parsed_ref[5:].partition("/")
        raw = _get_json(bucket, key)
    if raw is None:
        raw = _get_json(DERIVED_BUCKET, _cache_key(corpus_key))
    return normalize(raw) if raw is not None else None


def document_as_files(corpus_key: str, view: dict[str, Any]) -> dict[str, str]:
    """Render a parsed view as virtual files for the deepagents filesystem.

    One file per page keeps grep/read_file page-addressable so analysts can
    cite (key, page) accurately: `<safe_key>/page-0003.md`.
    """
    safe = corpus_key.replace("/", "__")
    files: dict[str, str] = {}
    if view["kind"] == "extraction":
        files[f"{safe}/extraction.json"] = json.dumps(
            {
                "source_key": corpus_key,
                "fields": view["extraction"]["fields"],
                "field_page_citations": view["extraction"]["field_pages"],
            },
            indent=1,
        )
        return files
    for page in view["pages"]:
        header = f"<!-- source: {corpus_key} | page: {page['page']} -->\n\n"
        files[f"{safe}/page-{page['page']:04d}.md"] = header + page["markdown"]
    return files
