"""Build the deepagents orchestrator with per-document-class analyst SubAgents.

Analyst SubAgent configs are generated programmatically from the repo's open
knowledge table (references/analyst-classes.json) — never hand-rolled routing.
All model calls route through the Vercel AI Gateway.
"""

import json
import os
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from langchain_openai import ChatOpenAI

GATEWAY_BASE_URL = "https://ai-gateway.vercel.sh/v1"
DEFAULT_MODEL = os.environ.get("ANALYST_MODEL", "anthropic/claude-sonnet-5")

# parents[5] = the repo root (…/eve-agents) when run from a source checkout.
_CLASSES_PATH = Path(
    os.environ.get(
        "ANALYST_CLASSES_PATH",
        Path(__file__).resolve().parents[5] / "references" / "analyst-classes.json",
    )
).resolve()


def _gateway_model(model_id: str) -> ChatOpenAI:
    api_key = os.environ.get("AI_GATEWAY_API_KEY") or os.environ.get("VERCEL_OIDC_TOKEN")
    if not api_key:
        raise RuntimeError("Set AI_GATEWAY_API_KEY (or VERCEL_OIDC_TOKEN) for gateway auth")
    return ChatOpenAI(model=model_id, base_url=GATEWAY_BASE_URL, api_key=api_key)


ANALYST_PROMPT = """You are the {name} for a well-file document corpus.
Scope: {description}

You analyze parsed documents seeded into your filesystem. Each markdown file
is one page of one source document, in a directory named after a mangled
form of the source key. The AUTHORITATIVE source key and page number are in
the HTML comment header inside each page file (and in `source_key` inside
extraction JSONs) — always cite from the header, never from the directory
name. Extraction JSONs carry `field_page_citations`.

Rules:
- Every factual claim must cite (source_key, page) from a file you actually read.
- Quote key figures verbatim. If pages disagree, report both.
- If the seeded files cannot answer the question, say exactly what is missing.
- Never invent content for unreadable or missing documents.

Return: your findings as concise bullet points, each ending with its
(source_key, page) citation, then a one-line confidence note.
"""


def load_analyst_classes(path: Path | None = None) -> list[dict[str, Any]]:
    data = json.loads((path or _CLASSES_PATH).read_text())
    return data["classes"]


def build_subagents(classes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": cls["name"].replace("_", "-"),
            "description": (
                f"{cls['description']} Handles entry_types: {', '.join(cls['entry_types'])}. "
                "Delegate when the question touches these document classes."
            ),
            "system_prompt": ANALYST_PROMPT.format(
                name=cls["name"].replace("_", " "), description=cls["description"]
            ),
            "model": _gateway_model(DEFAULT_MODEL),
        }
        for cls in classes
    ]


ORCHESTRATOR_PROMPT = """You are the analysis orchestrator for a well-file
document corpus. The caller (a durable front-door agent) sends one question
plus a set of already-parsed documents seeded into your filesystem, one file
per page (`<mangled_key>--<digest>/page-NNNN.md`) or one extraction JSON per
document. The true source key for citations is the HTML comment header in
each page file / the `source_key` field in extraction JSONs.

Work method:
1. `ls` the filesystem to see which documents and entry_types you received
   (the caller labels each document's entry_type in its manifest file).
2. Delegate page-level analysis to the analyst subagent whose scope matches
   each document class. Split cross-class questions across analysts.
3. Synthesize analyst findings into one answer. Keep only claims that carry
   a (source_key, page) citation; drop or re-verify anything uncited.
4. If the seeded documents cannot answer the question, say so precisely.

Your final message MUST be valid JSON:
{"answer": "<the answer>",
 "citations": [{"key": "<source_key>", "page": <n>}, ...],
 "analyst_notes": "<one short paragraph on method and confidence>"}
"""


def build_agent():
    classes = load_analyst_classes()
    return create_deep_agent(
        model=_gateway_model(DEFAULT_MODEL),
        system_prompt=ORCHESTRATOR_PROMPT,
        subagents=build_subagents(classes),
    )
