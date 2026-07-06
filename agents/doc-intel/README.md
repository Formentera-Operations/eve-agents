# doc-intel

Document-intelligence agent over a 500-file WellDrive corpus sample
(`corpus/sample-manifest.csv` at the repo root). Two layers, one seam
(see `decisions/2026-07-05-doc-intel-seam.md`):

- **eve agent** (this directory) — durable front door: corpus navigation
  tools, page-cited document reads, triage/citation skills.
- **analysts service** (`analysts/`) — Python deepagents layer with seven
  per-document-class analyst SubAgents generated from
  `references/analyst-classes.json`.

## Run locally

Two processes:

```bash
# 1. the analyst service (needs AWS creds + AI_GATEWAY_API_KEY or VERCEL_OIDC_TOKEN)
cd analysts && uv sync
uv run uvicorn doc_intel_analysts.service:app --port 8734

# 2. the eve agent (from this directory)
npx eve dev            # interactive TUI
npx eve dev --no-ui    # headless, for scripted verification
```

Model auth comes from `.env.local` (created by `npx vercel link` +
`npx vercel env pull .env.local`; eve reads it automatically, the Python
service needs it exported). The Vercel team must have AI Gateway billing
enabled — without it every model call fails with
`customer_verification_required`.

Environment knobs: `DOC_INTEL_ANALYSTS_URL` (default `http://127.0.0.1:8734`),
`WELLDRIVE_MANIFEST` (default `../../corpus/sample-manifest.csv`),
`ANALYST_MODEL` (default `anthropic/claude-sonnet-5`; per-class overrides via the optional `model` field in `references/analyst-classes.json` — logs analyst runs Haiku), `ANALYST_CLASSES_PATH`.

Parse-on-demand uses LiteParse (`@llamaindex/liteparse`) — a local, in-process
parser with no API key and no cost. OCR routing is automatic via `isComplex`.

## Verify

```bash
npx eve info      # 0 diagnostics; tools discovered
pnpm typecheck
pnpm test         # unit tests, no credentials needed
```

Benchmark (once model auth works): `benchmark/` at the repo root holds the
25-question ground-truth set and grading rules.
