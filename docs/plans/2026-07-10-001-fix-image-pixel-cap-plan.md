---
title: Image Pixel Cap and Terminal Skips - Plan
type: fix
date: 2026-07-10
topic: image-pixel-cap
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
---

# Image Pixel Cap and Terminal Skips - Plan

## Goal Capsule

- **Objective:** Replace PIL's stock decompression-bomb guard in the doc-intel image ingest path with a project-owned 600 MP bound so legitimate large well-log scans parse, and make deterministic image failures terminal, legibly-reasoned skips instead of forever-retried failures.
- **Product authority:** Rob (scope confirmed 2026-07-10; plan-time image-gate-only scoping confirmed same day).
- **Stop conditions:** Surface rather than guess if implementation reveals the ledger routing does not behave as the Planning Contract describes, or if the live acceptance pass produces any outcome other than 5 complete / 4 skipped.
- **Open blockers:** None.

---

## Product Contract

### Summary

Set the image ingest path's pixel bound to a project-owned 600-megapixel ceiling checked from header dimensions before decode. Images above the ceiling, and images PIL cannot identify, become terminal skips with legible ledger reasons. This admits the five FP GRIFFIN TIF well logs and retires all nine currently flapping failed rows.

### Problem Frame

Five FP GRIFFIN TIF well logs (189–280 megapixels) fail ingest because PIL's default decompression-bomb guard rejects anything above ~179 megapixels. The rejection fires from header metadata at open time — no memory has been spent — and everything admitted is thumbnailed to a bounded JPEG regardless of source size, so the only real cost of admitting a large image is its transient decode (~3 bytes per pixel).

The failure mode is worse than a missing document: these land as retriable failures, so every ingest pass re-fetches them from S3 and re-fails them, forever. Four more reopened rows share the flap with a different cause — clipboard-paste PNGs PIL cannot identify at all. Both are deterministic content failures cycling through a retry loop built for transient errors.

### Key Decisions

- **Own guard with terminal skip, not a bare cap raise.** Raising `Image.MAX_IMAGE_PIXELS` alone would admit the five TIFs but leave anything above the new cap flapping as a retriable failure. Instead the pipeline owns the check: read dimensions from the header, admit up to the ceiling, and above it return a terminal skip carrying the dimensions — the same legible, one-time verdict format-gate skips get.
- **Ceiling at 600 megapixels.** More than 2× the largest known legitimate file (280 MP), so the next longer log strip clears it without revisiting the constant, while bounding worst-case transient decode near 1.8–2.4 GB depending on source mode (see R5) on a machine with jetsam history. Rejected: 400 MP (a modestly longer scan re-trips it) and 1 GP (3–4 GB transient decode alongside concurrent ingest memory).
- **Unidentifiable images fold into the same fix.** PIL's failure to identify an image is deterministic; retrying never helps. Same terminal-skip semantics, and one change clears the entire nine-row flap set.
- **Transient errors keep retriable semantics.** Only the two deterministic classes (oversize, unidentifiable) become terminal. A blanket "all image errors are terminal" was considered and rejected — it would terminally skip files that failed for genuinely transient reasons.
- **Terminal content-skips are checksum-scoped.** A skip settles only the exact bytes it judged; a file fixed upstream arrives with a new checksum and re-ingests automatically on the next pass. The manual retry path remains available but is not required for reopening.

### Requirements

- R1. Images up to the project ceiling of 600 megapixels parse through the image ingest path; the five FP GRIFFIN TIF well logs (189–280 MP) ingest successfully.
- R2. An image above the ceiling produces a terminal skip whose ledger reason includes the image's pixel dimensions, never a retriable failure.
- R3. An image PIL cannot identify produces a terminal skip with an unreadable-image reason, never a retriable failure.
- R4. The oversize check reads dimensions from image header metadata before decode; memory is spent only on admitted images.
- R5. The ceiling is a named constant documenting its memory rationale: convert-to-RGB copies the decoded buffer, so peak transient decode ≈ (source bytes per pixel + 3) × pixels — 600 MP peaks at ~1.8 GB for RGB sources (convert skipped per KTD1) and ~2.4 GB for grayscale.
- R6. Transient failures (fetch errors, interrupted reads) retain existing retriable-failure semantics; terminal verdicts apply only to the deterministic classes in R2 and R3.

### Acceptance Examples

- AE1. **Covers R1.** Given the 280 MP FP GRIFFIN ALDRIDGE TIF, when an ingest pass processes it, then it parses to pages with a bounded JPEG screenshot like any other image.
- AE2. **Covers R2.** Given a hypothetical 700 MP image, when an ingest pass processes it, then the ledger records a terminal skip naming its dimensions, and subsequent ETag-bearing passes settle it without re-fetching.
- AE3. **Covers R3.** Given one of the four MCCALLISTER clipboard-paste PNGs, when an ingest pass processes it, then the ledger records a terminal unreadable-image skip, and subsequent ETag-bearing passes settle it without re-fetching.

### Success Criteria

- A retry pass over the nine currently flapping rows resolves all nine: five parse, four terminally skip. No row from that set fails again on a subsequent pass.

### Scope Boundaries

- No tiled or progressive decoding (pyvips or TIF tile reading) — a new dependency is disproportionate for this population.
- No change to failed-row retry semantics beyond the two deterministic image classes named here.
- No recovery attempt for the four unreadable PNGs' content — if their content matters, upstream re-export is the fix.
- Terminal classification applies to the standalone-image gate only. A PDF whose embedded figure or page screenshot trips the same oversize/unreadable errors keeps retriable semantics — one corrupt figure must not terminally skip a whole PDF.

### Sources

- Failure evidence: the local evidence store's retry report (`retry-parse-failures.json`) lists all nine rows with exact pixel counts and PIL error text.
- Rejection site and bounded-JPEG behavior: `agents/doc-intel/analysts/src/doc_intel_analysts/evidence/parse.py` (`_to_jpeg`, `parse_document`'s catch-all that marks image failures retriable).
- Retry/skip ledger semantics: `docs/solutions/logic-errors/ingest-ledger-conflates-parse-failures-with-skips.md` — "failed" is retriable every pass; "skipped" is reserved for terminal verdicts.

---

## Planning Contract

**Product Contract preservation:** changed one Key Decision — "Terminal content-skips do not auto-reopen" became "Terminal content-skips are checksum-scoped" after research showed `needs_ingest` settles a skipped row only for a matching checksum, so upstream-fixed files re-ingest automatically. Scope Boundaries gained the image-gate-only bullet confirmed at plan time. Review corrections (confirmed 2026-07-10): the ceiling Key Decision and R5 memory figures now account for convert-to-RGB copying the decoded buffer, and AE2/AE3's no-re-fetch wording is scoped to ETag-bearing passes. Ceiling value and all R/AE IDs unchanged.

### Key Technical Decisions

- **KTD1. The guard lives in `_to_jpeg`, replacing PIL's.** Neutralize `Image.MAX_IMAGE_PIXELS` at the PIL usage site and check `width × height` against a new `IMAGE_PIXEL_CEILING = 600_000_000` module constant immediately after `Image.open`, before any decode. `Image.open` reads only the header, so the check satisfies R4 at zero memory cost. Above the ceiling, raise a dedicated oversize exception carrying the dimensions. Convert to RGB only when `img.mode` is not already RGB — PIL's convert returns a copy while the decoded source is still alive, so an unconditional convert doubles peak memory; skipping it for RGB sources makes ~1.8 GB the true 600 MP peak. Because `_to_jpeg` is shared, PDF page screenshots and embedded figures get the same 600 MP protection as a side effect.
- **KTD2. Terminal classification happens in `parse_document`'s exception handling, scoped by gate.** The oversize exception and PIL's `UnidentifiedImageError` produce `SkipRecord(retriable=False)` only when the gate is `image`. Any other gate (a PDF whose figure bytes are corrupt or oversize) keeps the existing `retriable=True` path — deterministic-or-not, a per-figure failure must not terminally skip a multi-page PDF. Update the `SkipRecord.retriable` comment, which currently claims `False` is exclusively a format-gate verdict.
- **KTD3. No ingest or ledger changes.** `run_ingest` already forks on `result.retriable`: `False` routes to `record_skip(result, checksum)` — status `skipped`, checksum-bound, settled by `needs_ingest` on subsequent passes, auto-reopened if the upstream bytes change. The branch is live code that has simply never received a non-retriable parse result. The fix is entirely a parse-layer classification change. The no-re-fetch guarantee in AE2/AE3 holds for ETag-bearing passes (prefix listings): `run_ingest`'s pre-fetch short-circuit requires an entry ETag, and `manifest_entries` supplies none — a manifest pass re-fetches bytes, then settles as unchanged without re-parsing. The live settlement gate therefore proves settlement (`unchanged=9`), not fetch avoidance.
- **KTD4. Keep PIL imports lazy.** `parse.py` imports PIL inside `_to_jpeg` today; the new exception handling should not promote PIL to a module-level import. Import `UnidentifiedImageError` where it is caught, or wrap both deterministic cases in project-defined exception types raised from within the PIL-touching code.

### Assumptions

- PIL raises its decompression-bomb error from header dimensions at `Image.open`; disabling `MAX_IMAGE_PIXELS` is process-global, but the only other PIL open site (the CLIP embedder in `evidence/store.py`) consumes JPEGs this module already bounded to 2200 px, so the project ceiling in `_to_jpeg` is the sole effective guard.
- The five TIFs decode within memory tolerances (with the mode-conditional convert, worst case ≈ 1.1 GB transient for a 280 MP grayscale source, ~840 MB for RGB); no streaming decode is needed at this population.

---

## Implementation Units

### U1. Pixel ceiling and deterministic-failure classification in parse

- **Goal:** Oversize and unidentifiable standalone images become terminal `SkipRecord`s; images between PIL's old cap and 600 MP parse normally.
- **Requirements:** R1, R2, R3, R4, R5, R6.
- **Dependencies:** None.
- **Files:** `agents/doc-intel/analysts/src/doc_intel_analysts/evidence/parse.py`, `agents/doc-intel/analysts/tests/test_evidence_parse.py`.
- **Approach:** Implement KTD1, KTD2, and KTD4. Skip reasons follow the existing `"{gate} parse failed: …"` shape closely enough that ledger greps stay uniform: oversize reasons name width × height and the ceiling; unreadable reasons name the unidentifiable verdict.
- **Patterns to follow:** Existing tests in `test_evidence_parse.py` call `parse.parse_document` directly with crafted bytes (`tiny_jpeg()` helper, `test_corrupt_pdf_fails_into_skip_not_exception`, `test_xlsx_lands_in_skips_with_reason`) — mirror that shape; no store, no network.
- **Test scenarios:**
  - Happy path: a normal image still parses to one page with a bounded JPEG screenshot (existing `test_standalone_image_gets_screenshot_only` keeps passing).
  - Covers AE2 (parse half): an image header declaring more than 600 MP (a crafted header-only fixture, e.g. a BMP header with huge declared dimensions and no pixel data) returns a `SkipRecord` with `retriable=False` whose reason contains the declared dimensions — and contains the project's reason text, not PIL's "decompression bomb" message, proving PIL's guard was replaced rather than merely survived.
  - Boundary via patched ceiling: with `IMAGE_PIXEL_CEILING` monkeypatched below `tiny_jpeg()`'s pixel count, the same fixture skips terminally; at a ceiling equal to its pixel count, it parses (boundary is strictly-above).
  - Covers AE3 (parse half): non-image bytes under a `.png` key return `SkipRecord` with `retriable=False` and an unreadable-image reason.
  - Error-path scoping: a PDF whose parse raises `UnidentifiedImageError` or the oversize error (monkeypatch `_parse_pdf` to raise) returns `SkipRecord` with `retriable=True` — the terminal classification is image-gate-only.
  - Transient unchanged: a non-deterministic exception from the image path (monkeypatch `_to_jpeg` to raise `OSError`) still returns `retriable=True` (R6).
- **Verification:** New and existing tests pass in `agents/doc-intel/analysts` via `uv run pytest tests/test_evidence_parse.py`; full suite stays green.

### U2. Pass-level proof that terminal parse skips settle the ledger

- **Goal:** Prove the parse-layer classification produces the intended ledger behavior end to end: terminal skip with checksum on first pass, no re-fetch on the second.
- **Requirements:** R2, R3; Success Criteria mechanics.
- **Dependencies:** U1.
- **Files:** `agents/doc-intel/analysts/tests/test_evidence_store.py` (existing `evidence.ingest` coverage lives here).
- **Approach:** Drive `run_ingest` with a stubbed fetch over entries carrying a listing ETag (prefix-mode shape: key, asset_team, etag) whose bytes are unidentifiable; assert the report and ledger rather than parse internals. Only the ETag pre-fetch short-circuit avoids the fetch call — manifest-shaped entries without ETags re-fetch every pass.
- **Test scenarios:**
  - Covers AE3 (ledger half): first pass over an unidentifiable `.png` entry reports `skipped=1, failed=0` and the ledger row is status `skipped` with a non-empty checksum.
  - Covers AE2/AE3 (no re-fetch): a second pass over the same ETag-bearing entry reports `unchanged=1` and the fetch stub is not called again.
  - Reopen-on-change: the same key with different bytes (new checksum) is fetched and re-processed, confirming checksum-scoped terminality.
- **Verification:** `uv run pytest tests/test_evidence_store.py` green; scenarios assert on the pass report counters and ledger status, matching existing test style.

### U3. Documentation refresh for the new skip semantics

- **Goal:** The three places that document "parse failures are always retried" reflect the two deterministic exceptions.
- **Requirements:** R2, R3 (documentation accuracy).
- **Dependencies:** U1.
- **Files:** `CONCEPTS.md` (Ingest Ledger entry), `docs/solutions/logic-errors/ingest-ledger-conflates-parse-failures-with-skips.md`, `references/evidence-store.md`.
- **Approach:** One-line-scale edits: failures are retried *except* deterministic image verdicts (oversize beyond the project ceiling, unreadable bytes), which are terminal for the judged checksum. Keep each document's existing voice; do not restructure.
- **Test scenarios:** Test expectation: none — documentation-only unit.
- **Verification:** Grep the three files for "always retried"-shaped claims; none survive unqualified.

---

## Verification Contract

| Gate | Command | Applies to | Pass signal |
|---|---|---|---|
| Python suite | `uv run pytest` from `agents/doc-intel/analysts` | U1, U2 | All tests pass (101 pre-change + new) |
| Workspace bar | `pnpm typecheck && pnpm test` from repo root | All | Green (TS untouched but required before declaring done) |
| Live acceptance | Ingest pass over a 9-key manifest built from the retry report: `uv run python -m doc_intel_analysts.evidence.ingest --manifest <nine-keys.csv>` | Success Criteria | Report shows `complete=5, skipped=4, failed=0` |
| Settlement | Re-run the same 9-key pass | Success Criteria | Report shows `unchanged=9, failed=0` |

The live acceptance gates need the local evidence store and AWS credentials; if unavailable at implementation time, land the code with unit/integration proof and record the live pass as pending.

## Definition of Done

- U1–U3 landed; Python suite and workspace bar both green.
- Live acceptance and settlement gates met, or explicitly recorded as pending with the reason.
- The `SkipRecord.retriable` comment and the three documentation targets no longer claim parse failures are unconditionally retried.
- No leftover experimental code from abandoned approaches in the diff.
- Work committed on a feature branch and pushed; PR opened per repo convention.
