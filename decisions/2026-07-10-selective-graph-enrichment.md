# Selective graph enrichment — pilot complete, pattern adopted, economics measured

**Status:** ACCEPTED (Rob, 2026-07-10). The Bull Mountain pilot is closed;
evidence-nominated enrichment is the standing pattern for growing the
knowledge graph. Extends `2026-07-05-doc-intel-seam.md` (three-legged
retrieval) and `2026-07-09-evidence-store-migration.md` (Phase 4 hosts
future rebuilds).

**Decision recorded:** the knowledge graph grows by **selective
enrichment** — the evidence store nominates entity-dense documents, the
graph interprets only those — never by brute-force corpus ingest. Ontology
changes are **batched** ahead of rebuilds rather than triggering them,
because a rebuild is the expensive unit of work (~$95, ~2 h at current
scope) and runs on Phase 4 server hardware once available.

## Pilot results (Bull Mountain pad, 2026-07-09/10)

- **Nomination** (`.evidence/pilot-bull-mountain-manifest.csv`): 12,845
  pad documents → 1,297 nominated — telemetry excluded (LWD, directional,
  PVA ≈ 90% of pages, near-zero entity density), Frac PDFs only, checksum
  dedupe dropped 1,603 pad-level duplicates (55% of the nominated set).
- **Ingest**: 1,296/1,297 ok via `graph.ingest --from-evidence` (PR #21);
  graph grew 6,442 → **23,924 nodes**, 26,628 → **221,785 edges**.
- **Validation**: 293 ontology-valid of a measured **matchable ceiling of
  337 (86.9%)**, with **zero runtime matcher misses** — the entire gap was
  missing individuals, closed by the pass-2 regeneration (PR #22, merged
  2026-07-10: 462 individuals, incl. the triple-verified IPT → NEW IPT INC
  alias, with alias rows minted unconditionally so documented d/b/a
  spellings match the first time they appear). The ceiling grew only ~10%
  while interpreted text grew ~5× — extraction noise scales with volume;
  the matchable population does not.
- **Behavior**: the cross-leg tandem verified live and locked in as
  `evals/graph-pad-tandem.eval.ts` (PR #23, merged 2026-07-10) — graph-first
  recall, page verification through `evidence_doc_ids` with a required page
  marker, unverifiable claims dropped.

## Measured economics (gateway dashboard, 24 h window covering the pilot)

| Item | Value |
|---|---|
| Total spend | **$94.20** (haiku-4.5 extraction $90.83; embeddings $2.43; sonnet vision $0.93) |
| Work covered | trial (25 docs) + sample rebuild (311 docs, 4.9M chars) + pilot (1,297 docs, 24.4M chars) + interruption redo |
| Token amplification | **~9×** — 68M gateway tokens against ~7.3M tokens of source text (multi-pass extraction; structured-JSON output tokens dominate at Haiku's 5× output rate) |
| Unit costs | **≈ $3.2 per MB of source text; ≈ 5.6¢ per entity-dense document** |
| Wall clock | sample 10.5 min; pilot ~90 min of cognify (interruption-resumable per data item) |

**What these numbers price:**
- A full rebuild at current scope ≈ **$95 / ~2 h** → rebuilds are periodic
  and batched, not per-ontology-tweak; they belong on the Phase 4
  Container Apps Job.
- Brute-forcing the full indexed Westlake tranche (32,946 docs, dominated
  by telemetry) would have cost roughly an order of magnitude more for
  almost no additional matchable entities — the pilot's exclusions saved
  ~90% of spend, which is the selective-enrichment thesis in dollars.
- Estimation rule learned: budget from **source MB × 9× amplification at
  the extraction model's blended rate**, not from source tokens alone.
  (Pre-pilot estimate of $10–25 missed the amplification and the output-
  token weighting.)

## Operational lessons folded in

- The gateway **credit balance is the binding constraint**, not compute:
  the pilot stalled at $0 mid-run (retries exhausted; resumed cleanly
  after top-up). Phase 3's team-scope billing with headroom management is
  now load-bearing, not cosmetic.
- Long ingests launch detached (`nohup` + `disown`) — session-owned
  background tasks were killed twice by harness interrupts.
- cognee's per-item run qualification makes interrupted cognify safely
  resumable; interruption costs re-work only within the in-flight document.

**Alternatives considered:** brute-force full-corpus ingest (rejected —
priced above); per-change rebuilds (rejected — $95/change buys nothing a
batched rebuild doesn't).

**Trade-offs accepted:** validation counts lag ontology changes until the
next batched rebuild (currently: 462 individuals banked, counts move at
the Phase 4 rebuild, expected ≈ ceiling); graph coverage remains
deliberately partial — the evidence store answers for everything else.

**Owner:** Rob (rebuild cadence, next enrichment targets).
