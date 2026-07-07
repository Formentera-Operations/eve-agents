"""Evidence store configuration with the same hard egress guard as the graph
leg (KTD1, KTD3).

Two model paths exist here and only one leaves the machine:

- Text embeddings call the Vercel AI Gateway. The endpoint is validated with
  the graph leg's host-equality primitive before any client is constructed —
  a non-gateway endpoint raises, it never silently egresses.
- Image embeddings run on local OpenCLIP. No document content leaves the
  process; the pretrained weights are fetched once from the model CDN at
  environment setup (see `prefetch_clip_weights`) and cached, so steady-state
  inference is fully offline.

The store lives under `analysts/.evidence/` — deliberately OUTSIDE
`.cognee/`, which graph rebuilds wipe.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from doc_intel_analysts.graph.config import GATEWAY_BASE_URL, gateway_host_problem

# Store roots live under the package, gitignored (same discipline as .cognee).
_PACKAGE_ROOT = Path(__file__).resolve().parents[3]
STORE_ROOT = _PACKAGE_ROOT / ".evidence"
LANCE_ROOT = STORE_ROOT / "lance"
PARSED_ROOT = STORE_ROOT / "parsed"

# Raw corpus bucket (source archive). The Python layer historically read only
# the derived bucket (corpus.DERIVED_BUCKET); evidence ingest is the first
# consumer of raw objects on this side of the seam.
RAW_BUCKET = "formentera-welldrive"

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIMENSIONS = 1536
# "-quickgelu" matches the openai checkpoint's activation; plain ViT-B-32
# loads the same weights but warns about a QuickGELU config mismatch.
DEFAULT_CLIP_MODEL = "ViT-B-32-quickgelu"
DEFAULT_CLIP_PRETRAINED = "openai"


class EvidenceConfigError(RuntimeError):
    """Raised when the environment would let content leave the gateway path."""


@dataclass(frozen=True)
class EvidenceConfig:
    gateway_base_url: str
    gateway_api_key: str
    embedding_model: str
    embedding_dimensions: int
    clip_model: str
    clip_pretrained: str
    store_root: Path
    lance_root: Path
    parsed_root: Path


def load_config() -> EvidenceConfig:
    """Resolve and validate the evidence environment. Fail-loud, no defaults
    that egress: a missing credential or a non-gateway endpoint raises before
    any embedding client initializes."""
    key = os.environ.get("AI_GATEWAY_API_KEY") or os.environ.get("VERCEL_OIDC_TOKEN")
    if not key:
        raise EvidenceConfigError(
            "No gateway credential: set AI_GATEWAY_API_KEY or VERCEL_OIDC_TOKEN."
        )

    endpoint = os.environ.get("EVIDENCE_EMBEDDING_ENDPOINT", GATEWAY_BASE_URL)
    problem = gateway_host_problem(endpoint, "EVIDENCE_EMBEDDING_ENDPOINT")
    if problem:
        raise EvidenceConfigError(
            "Refusing to initialize the evidence store; content could leave "
            "the gateway path: " + problem
        )

    config = EvidenceConfig(
        gateway_base_url=endpoint,
        gateway_api_key=key,
        embedding_model=os.environ.get(
            "EVIDENCE_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL
        ),
        embedding_dimensions=int(
            os.environ.get(
                "EVIDENCE_EMBEDDING_DIMENSIONS", str(DEFAULT_EMBEDDING_DIMENSIONS)
            )
        ),
        clip_model=os.environ.get("EVIDENCE_CLIP_MODEL", DEFAULT_CLIP_MODEL),
        clip_pretrained=os.environ.get(
            "EVIDENCE_CLIP_PRETRAINED", DEFAULT_CLIP_PRETRAINED
        ),
        store_root=STORE_ROOT,
        lance_root=LANCE_ROOT,
        parsed_root=PARSED_ROOT,
    )
    config.lance_root.mkdir(parents=True, exist_ok=True)
    config.parsed_root.mkdir(parents=True, exist_ok=True)
    return config


def prefetch_clip_weights(config: EvidenceConfig | None = None) -> None:
    """Download and cache the OpenCLIP pretrained weights (one-time setup).

    This is the single sanctioned external fetch on the image path — model
    weights from the OpenCLIP CDN, never document content. Run it at
    environment setup so steady-state inference needs no network.
    """
    config = config or load_config()
    import open_clip

    open_clip.create_model_and_transforms(
        config.clip_model, pretrained=config.clip_pretrained
    )
