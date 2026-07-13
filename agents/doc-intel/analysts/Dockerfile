# syntax=docker/dockerfile:1.7
# doc-intel analysts: one linux/amd64 image serving the FastAPI seam (uvicorn)
# and the batch-module entrypoints (ACA Jobs).
#
# Build from the REPO ROOT — the package resolves repo-root assets by relative
# depth (Path(__file__).parents[N]), so the tree inside the image must mirror
# a source checkout:
#   docker buildx build --platform linux/amd64 \
#     -f agents/doc-intel/analysts/Dockerfile -t doc-intel-analysts:dev .
#
# Command convention: plain CMD, no ENTRYPOINT. The default CMD serves the
# service on 8734; ACA Jobs override the whole command cleanly, e.g.
#   command: ["python", "-m", "doc_intel_analysts.evidence.ingest", ...]

FROM --platform=linux/amd64 python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

# uv pinned >= 0.10: the committed uv.lock is revision 3, which older series
# (e.g. the gis-extractor sibling's 0.5) cannot parse.
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv

# Non-root from the start (deviation from the sibling, which syncs as root and
# chowns /app afterwards — that would duplicate a torch-sized venv into an
# extra image layer). -m: open_clip caches the baked weights under $HOME.
RUN useradd -r -m -u 1000 appuser
USER appuser

WORKDIR /app/agents/doc-intel/analysts

# Dependencies first (torch dominates this layer) so source edits don't
# re-download the world. --locked: the committed lock is the contract.
COPY --chown=appuser:appuser agents/doc-intel/analysts/pyproject.toml agents/doc-intel/analysts/uv.lock ./
RUN uv sync --no-dev --locked --no-install-project

# The package plus repo-root assets at source-checkout depths:
#   parents[3] from evidence/config.py + graph/config.py -> this directory
#   parents[5] from agent.py / corpus.py                 -> /app (repo root)
#   parents[6] from graph/ingest.py / individuals.py     -> /app (repo root)
# .masters/ is deliberately NOT copied: gitignored laptop state that rides the
# NFS share in production (KTD3) — the image builds from a clean checkout.
COPY --chown=appuser:appuser agents/doc-intel/analysts/src ./src
COPY --chown=appuser:appuser references/ /app/references/
COPY --chown=appuser:appuser corpus/sample-manifest.csv /app/corpus/sample-manifest.csv

# Editable install at full repo depth (uv's default; never --no-editable):
# the parents[N] resolution above depends on the source-tree layout — a
# site-packages install would silently relocate the store roots to an empty
# directory.
RUN uv sync --no-dev --locked

ENV PATH="/app/agents/doc-intel/analysts/.venv/bin:$PATH"

# Bake the OpenCLIP weights — the one sanctioned external fetch on the image
# path (model weights, never document content). The placeholder key satisfies
# load_config()'s fail-loud credential guard for this RUN line only; it never
# persists in the image env (runtime env comes from Terraform). load_config()
# also scaffolds .evidence/, so the store root is recreated empty afterwards:
# the three NFS mount points ship EMPTY and appuser-owned (no fsGroup on ACA).
RUN AI_GATEWAY_API_KEY=build-placeholder python -c "from doc_intel_analysts.evidence.config import prefetch_clip_weights; prefetch_clip_weights()" \
    && rm -r .evidence \
    && mkdir .evidence .cognee .masters

# Kuzu downloads its `json` extension into $HOME/.lbdb on first use — that
# happened on the dev laptop long ago, so it was invisible until the NFS gate
# opened the graph store in Azure and failed loud (2026-07-13). Bake it:
# INSTALL fetches the shared object into /home/appuser/.lbdb; LOAD proves it
# links. The throwaway database never touches the mounts.
RUN python -c "import tempfile, kuzu; db = kuzu.Database(f'{tempfile.mkdtemp()}/ext-seed'); conn = kuzu.Connection(db); conn.execute('INSTALL json'); conn.execute('LOAD json'); print('kuzu json extension baked')"

EXPOSE 8734
CMD ["uvicorn", "doc_intel_analysts.service:app", "--host", "0.0.0.0", "--port", "8734"]
