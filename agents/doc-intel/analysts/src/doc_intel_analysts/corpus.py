"""Read parsed document content from the derived S3 bucket.

Mirrors the eve agent's lib/parsed.ts normalization: pilot tier-A extraction
runs and tier-B/C parse runs (plus doc-intel cache entries) become one view.
Document bodies never transit the eve↔analysts seam — this module is how the
analyst side reads them directly.
"""

import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import boto3

DERIVED_BUCKET = "formentera-welldrive-derived"
PARSE_CACHE_PREFIX = "runs/doc-intel/parsed/"

# parents[5] = the repo root (…/eve-agents) when run from a source checkout.
_MANIFEST_PATH = Path(
    os.environ.get(
        "WELLDRIVE_MANIFEST",
        Path(__file__).resolve().parents[5] / "corpus" / "sample-manifest.csv",
    )
)

_s3 = boto3.client("s3")
_manifest_refs: dict[str, str] | None = None


def _manifest_parsed_refs() -> dict[str, str]:
    """key -> parsed_ref from the corpus manifest (the service's own copy).

    The caller's parsed_ref is untrusted and is never used for reads: a
    direct caller could otherwise pair any corpus key with any parse output
    and have foreign content rendered under a citation key of their choice.
    """
    global _manifest_refs
    if _manifest_refs is None:
        with _MANIFEST_PATH.open(newline="") as f:
            _manifest_refs = {row["key"]: row["parsed_ref"] for row in csv.DictReader(f)}
    return _manifest_refs


def _get_json(bucket: str, key: str) -> dict[str, Any] | None:
    try:
        body = _s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        return json.loads(body)
    except Exception:
        return None


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Return {kind, pages: [{page, markdown}], extraction?, page_count}."""
    if isinstance(raw.get("pages"), list) and raw.get("kind") in ("markdown", "extraction"):
        # doc-intel cache entries are written by the TypeScript tool in
        # camelCase (pageCount); serve them in this module's snake_case.
        return {
            "kind": raw["kind"],
            "pages": raw["pages"],
            **({"extraction": raw["extraction"]} if raw.get("extraction") else {}),
            "page_count": raw.get("page_count", raw.get("pageCount", len(raw["pages"]))),
        }

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


def _allowed_parsed_ref(parsed_ref: str) -> str | None:
    """Return the S3 key iff the ref points at parse outputs we own.

    The service is directly reachable, so parsed_ref is untrusted input:
    without this gate a caller could make us read arbitrary S3 objects with
    our credentials and seed them into the analysis. All legitimate parse
    outputs live under runs/ in the derived bucket — nothing else is ever
    read through a parsed_ref.
    """
    if not parsed_ref.startswith("s3://"):
        return None
    bucket, _, key = parsed_ref[5:].partition("/")
    if bucket != DERIVED_BUCKET or not key.startswith("runs/"):
        return None
    return key


def fetch_document(corpus_key: str, parsed_ref: str | None = None) -> dict[str, Any] | None:
    """Fetch a document's parsed view.

    The parsed_ref is resolved from the service's own manifest — the
    caller-supplied value (kept in the seam contract for observability) is
    ignored for reads, so parse content is always bound to its true corpus
    key. Keys outside the manifest fall back to the shared hash-keyed cache
    only.
    """
    raw = None
    manifest_ref = _manifest_parsed_refs().get(corpus_key, "")
    if manifest_ref:
        key = _allowed_parsed_ref(manifest_ref)
        if key is not None:
            raw = _get_json(DERIVED_BUCKET, key)
    if raw is None:
        raw = _get_json(DERIVED_BUCKET, _cache_key(corpus_key))
    return normalize(raw) if raw is not None else None


def document_as_files(corpus_key: str, view: dict[str, Any]) -> dict[str, str]:
    """Render a parsed view as virtual files for the deepagents filesystem.

    One file per page keeps grep/read_file page-addressable so analysts can
    cite (key, page) accurately: `<safe_key>/page-0003.md`. The directory
    name carries a short digest of the true key because the `/` → `__`
    mangling alone is not injective (a real `__` in a key collides with a
    path separator); the digest keeps two distinct documents from silently
    overwriting each other. The authoritative source key is the header
    comment inside each page file, never the directory name.
    """
    digest = hashlib.sha256(corpus_key.encode()).hexdigest()[:8]
    safe = f"{corpus_key.replace('/', '__')}--{digest}"
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
