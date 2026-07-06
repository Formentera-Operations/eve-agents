"""Cognee environment configuration with a hard egress guard (KTD2, KTD4).

Everything here MUST run before the first `import cognee` anywhere in the
process — cognee reads env at import/first-use, initializes logging, and
resolves storage paths (venv-relative by default, which is why the roots are
set explicitly).

The guard is a house-rule enforcement point, not a convenience: cognee routes
LLM and embedding calls independently, and an unset group silently defaults
to api.openai.com — document-content egress outside the Vercel AI Gateway.
"""

import os
from pathlib import Path

GATEWAY_BASE_URL = "https://ai-gateway.vercel.sh/v1"

# File-based embedded stores live under the package, gitignored.
_PACKAGE_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = _PACKAGE_ROOT / ".cognee" / "data"
SYSTEM_ROOT = _PACKAGE_ROOT / ".cognee" / "system"

DATASET_NAME = "welldrive"


class GraphConfigError(RuntimeError):
    """Raised when the environment would let content leave the gateway path."""


def _gateway_key() -> str:
    key = os.environ.get("AI_GATEWAY_API_KEY") or os.environ.get("VERCEL_OIDC_TOKEN")
    if not key:
        raise GraphConfigError(
            "No gateway credential: set AI_GATEWAY_API_KEY or VERCEL_OIDC_TOKEN."
        )
    return key


def configure() -> None:
    """Set cognee's env, refusing any configuration that bypasses the gateway.

    Idempotent. Explicit env set by the operator wins, but only if it still
    points at the gateway; anything else raises rather than silently egressing.
    """
    key = _gateway_key()

    llm_model = os.environ.get("GRAPH_MODEL", "openai/anthropic/claude-haiku-4.5")
    # Bare id: tiktoken must map it for cognee's tokenizer, and the gateway
    # accepts un-prefixed OpenAI embedding ids (verified live).
    embedding_model = os.environ.get("GRAPH_EMBEDDING_MODEL", "text-embedding-3-large")

    defaults = {
        # LLM path — gateway only.
        "LLM_PROVIDER": "custom",
        "LLM_MODEL": llm_model,
        "LLM_ENDPOINT": GATEWAY_BASE_URL,
        "LLM_API_KEY": key,
        # Embedding path — gateway only (unset silently means api.openai.com).
        "EMBEDDING_PROVIDER": "openai",
        "EMBEDDING_MODEL": embedding_model,
        "EMBEDDING_ENDPOINT": GATEWAY_BASE_URL,
        "EMBEDDING_API_KEY": key,
        "EMBEDDING_DIMENSIONS": "3072",
        "EMBEDDING_MAX_TOKENS": "8191",
        # The gateway rejects response_format json_object (instructor's
        # default json_mode for custom providers); tool_call works (verified
        # live against both candidate models).
        "LLM_INSTRUCTOR_MODE": "tool_call",
        # Session-memory caching feeds cached completions back into later
        # searches in the same session, poisoning CHUNKS provenance (the
        # cached item carries no belongs_to_set tags — observed live).
        "CACHING": "false",
        # No third egress path: telemetry off (var name verified against 1.2.2).
        "TELEMETRY_DISABLED": "1",
        # Embedded single-tenant stores with explicit roots (KTD4).
        "DB_PROVIDER": "sqlite",
        "GRAPH_DATABASE_PROVIDER": "kuzu",
        "VECTOR_DB_PROVIDER": "lancedb",
        "DATA_ROOT_DIRECTORY": str(DATA_ROOT),
        "SYSTEM_ROOT_DIRECTORY": str(SYSTEM_ROOT),
        "ENABLE_BACKEND_ACCESS_CONTROL": "false",
        "REQUIRE_AUTHENTICATION": "false",
    }
    for name, value in defaults.items():
        os.environ.setdefault(name, value)

    _assert_gateway_only()
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    SYSTEM_ROOT.mkdir(parents=True, exist_ok=True)


def _assert_gateway_only() -> None:
    """The three-part egress guard: LLM endpoint, embedding endpoint, telemetry."""
    problems = []
    for group in ("LLM", "EMBEDDING"):
        endpoint = os.environ.get(f"{group}_ENDPOINT", "")
        if not endpoint.startswith(GATEWAY_BASE_URL):
            problems.append(
                f"{group}_ENDPOINT is {endpoint!r} — must point at the Vercel AI Gateway"
            )
        if not os.environ.get(f"{group}_API_KEY"):
            problems.append(f"{group}_API_KEY is unset")
    if os.environ.get("TELEMETRY_DISABLED") not in ("1", "true", "True"):
        problems.append("TELEMETRY_DISABLED must be set — cognee telemetry is an egress path")
    if problems:
        raise GraphConfigError(
            "Refusing to initialize cognee; content could leave the gateway path: "
            + "; ".join(problems)
        )
