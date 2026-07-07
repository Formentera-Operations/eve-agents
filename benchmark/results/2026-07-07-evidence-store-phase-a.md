# 2026-07-07 — Evidence store Phase A gates (U6)

Sample-store build and two-layer benchmark for the evidence store
(plan: `docs/plans/2026-07-06-002-feat-evidence-store-plan.md`).

## Store build (sample manifest, 500 entries)

- 426 documents ingested (371 new + 55 from earlier resumable passes),
  74 skips — every one ledgered with a reason (Excel family, unsupported
  extensions, empty/corrupt files); **0 silent failures**.
- 2,922 pages, 46,723 chunks, 0 extracted assets (LiteParse's default
  image_mode extracts no embedded figures; figure capability rides
  page-screenshot CLIP vectors + answer-time vision instead).
- Store size: **955 MB** (~330 KB/page all-in: JPEG screenshot + text +
  vectors). JPEG pages measured 84–266 KB, inside the KTD5 0.5 MB bound.
- Ingest is ledger-driven and survived four interruptions across the run;
  re-runs processed only unfinished documents (KTD6 verified in anger).

## Retrieval layer (R8) — awaiting Rob's label-set approval

Question set: `benchmark/evidence-questions.json` — 20 questions
(6 figure / 4 table / 6 text / 4 text_native), all 31 expected-page labels
mechanically verified against the store; figure facts verified image-only
(e.g. `POLY PILL` appears in zero text layers store-wide).

Metrics (`uv run python -m doc_intel_analysts.evidence.benchmark`):

| Modality | n | any_page_hit@5 | page_coverage@5 | modality_hit@5 |
|---|---|---|---|---|
| text | 6 | 0.833 | 0.833 | 0.833 |
| table | 4 | 0.75 | 0.639 | 0.75 |
| text_native | 4 | 0.50 | 0.375 | 0.50 |
| figure | 6 | 0.00 | 0.00 | 0.00 |
| **overall** | **20** | **0.50** | **0.453** | **0.50** |

The figure zero is honest and structural: log-plot pages carry ~126 chars
of text (scale numbers), so no text signal can rank them, and CLIP
question-sentence similarity does not reach them either. The working
figure path is `find_evidence_files` (name/team) → `read_evidence` with a
question (vision) — proven at the answer layer below. Known label caveats
recorded for review: EQ-T4's answer repeats on 9 pages (any-page-hit is
the meaningful signal there); EQ-F5's wording is ambiguous (multiple
deflections exist in the log; see answer layer).

Two defects were found and fixed by this measurement pass (both committed):

- **Fusion**: summed RRF let pages appearing mid-list in three signals
  outrank a decisive rank-1 FTS hit; rewritten to KTD7's
  best-signal-wins with agreement as a tie-break.
- **Grep**: the raw-dataset column scan panicked in Rust at sample scale
  under the pinned lancedb 0.34/pylance 0.36; rewritten as `regexp_like`
  filter pushdown (same exactness, one code path).

## Answer layer (R9)

Procedure: live agent sessions via `POST /eve/v1/session` + NDJSON stream,
manually graded — same spot-verified procedure as the 2026-07-05 runs
(`benchmark/README.md`); no automated runner (deferred per KTD9).

- **25-question regression: 25/25 correct with verifiable citations.**
  9 automated-grader flags were all string-format artifacts (same pattern
  as runs 2/3), confirmed correct on manual reading. The agent organically
  used the new evidence tools in 12 of 25 answers; no regression.
- **20 evidence questions: 19/20 correct with page citations.**
  - All 6 figure questions answered through the evidence store; **EQ-F4 is
    the previously-unanswerable proof**: "where does the orange curve step
    right" answered "~400 ft" via `read_evidence` vision with the exact
    page-3 citation (Success Criteria satisfied).
  - EQ-F5 (the one miss): the agent found a *different, larger* leftward
    deflection (~7,800–8,040 ft, real cited pages) than the labeled
    770–785 ft instance — the question wording admits both. Label flagged
    for Rob's review (reword to "shallowest deflection" or accept both).
- **Evals (R11): graph-explore 4/4, delegation 4/4** with all four new
  tools discovered. Graph leg untouched and unregressed.

## Vision mechanism (KTD10 follow-through)

- eve 0.19 hard-rejects non-text/JSON tool model output (runtime
  TypeError, verified in source), so R7 vision is service-side —
  `decisions/2026-07-06-evidence-read-vision-mechanism.md`.
- Live accuracy check on SLWD log annotations: Haiku misread small depth
  labels (13,290 for 13,200; missed the poly pill); **Sonnet read all
  three exactly** → `DEFAULT_VISION_MODEL = anthropic/claude-sonnet-5`
  (on-demand reads; `EVIDENCE_VISION_MODEL` overrides).
- Pre-U3 CLIP domain experiment: 3/4 modality queries hit@5 over 20 real
  pages (log plots strong, regulatory strong, frac rank-3, BHA line
  diagrams missed) → per-page CLIP vectors kept in v1.

## Cost (Phase A)

Sample ingest embeddings (text-embedding-3-small, ~47k records) ≈ well
under $1; benchmark/eval agent runs + vision reads on the order of a few
dollars. Total Phase A spend is a rounding error against the $75 budget;
exact per-document projections for Westlake are computed at the U7
checkpoint from these measured numbers.

## Gate status

- [ ] R8 label set — **awaiting Rob's review** of
  `benchmark/evidence-questions.json` (incl. EQ-F5 rewording decision)
- [x] R9 answer bar — 25/25 regression; evidence questions 19/20 with
  page citations; figure-evidence success criterion met (EQ-F4 et al.)
- [x] R11 evals — 8/8 gates
- [ ] R10 cost+disk checkpoint — Phase B, presented separately with
  measured Westlake projections
