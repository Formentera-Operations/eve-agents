---
title: "Evidence-store ingest ledger conflated parse failures with format-gate skips — hidden and permanently unretriable"
date: 2026-07-09
category: logic-errors
module: doc-intel evidence store ingest ledger
problem_type: logic_error
component: database
symptoms:
  - "Two production ingest passes reported 0 failures while 9 documents had silently failed to parse"
  - "Parse exceptions were recorded via record_skip with a real content checksum, so needs_ingest treated them as terminal and never retried them"
  - "Parse and fetch failures incremented the 'skipped' counter instead of 'failed', so the headline failure metric was structurally blind to the entire parse layer"
  - "First-seen documents skipped the pre-insert delete, so a crash between row insert and ledger write could strand partial rows that a rerun would duplicate"
root_cause: logic_error
resolution_type: code_fix
severity: high
tags:
  - evidence-store
  - ingest-ledger
  - error-classification
  - retriability
  - idempotency
  - observability
  - checksum
  - adversarial-review
related_components:
  - background_job
---

# Evidence-store ingest ledger conflated parse failures with format-gate skips — hidden and permanently unretriable

## Problem

The doc-intel evidence-store ingest funneled two categorically different outcomes — deliberate format-gate skips and genuine parse-layer failures — into a single `SkipRecord` type recorded with a content checksum, which made parse failures permanently terminal (never retried) and invisible (counted as `skipped`, never `failed`). A related crash-safety hole let a process that died mid-document on a *first-seen* doc strand orphaned content rows that a rerun would then duplicate.

## Symptoms

- The ingest report's `failed` count and its `failures[]` list stayed empty even when real documents never made it into the store. A Westlake pass could print a clean `"failed": 0` headline while, per this session's investigation, 9 documents had actually errored out during parsing — the metric was structurally incapable of showing them.
- Documents that a user would expect to be retrievable were simply absent from search results, with nothing in the report or the ledger flagging them as problems. They looked identical to the ~5,100 documents the pipeline deliberately declined (Excel-family and other out-of-scope formats).
- Those 9 failures broke down as 5 legitimate TIFF well-log scans (189–280 megapixels) that Pillow's decompression-bomb guard refused to open — real evidence documents — and 4 clipboard-paste image files carrying invalid image bytes (genuine junk). All 9 were absorbed into `report["skipped"]` and, worse, written to the ledger with a checksum, so no subsequent pass would ever try them again.
- Separately, if a process was killed (e.g. the 2026-07-08 SIGTERM) in the narrow window after a first-seen document's rows were inserted but before its ledger row was written, the content tables held rows for a `doc_id` the ledger had never heard of. On the next run that document would be inserted a *second* time, silently doubling its pages/chunks/assets.

## What Didn't Work

Nothing was tried-and-reverted here; the more useful observation is *why this survived so long undetected*. The defect went through two full production passes over the Westlake corpus and an in-session verification pass without being caught, because the only signal anyone was watching — the `failed` count — was the exact thing the bug suppressed. Verification graded *answer quality* against a benchmark, not *ledger semantics*, so a document that was silently skipped simply never showed up to be graded; there was no failing observation to trace back. The failure mode was invisible by construction: the instrument that would have detected it was the instrument that was broken.

It took a **cross-provider adversarial review** to surface it. A Codex review of PR #12 flagged the parse-failure terminality/visibility defect; the sibling crash-window defect was found independently by both the Codex GitHub bot and the in-session verify pass — three reviewers converging on the same crash window. Author-aligned review kept re-reading the code the way it was intended to work; a reviewer with no stake in the original design read what it *actually* did.

## Solution

Shipped in **PR #12** (merged 2026-07-09), across two fix commits: parse-failure retry/visibility, and orphan reconciliation.

### 1. Give `SkipRecord` an explicit terminality signal

A single boolean now distinguishes "this file's bytes are not ingestable, ever" from "this attempt errored and may succeed later."

Before — one undifferentiated skip type (`parse.py`):

```python
@dataclass(frozen=True)
class SkipRecord:
    s3key: str
    doc_id: str
    reason: str
```

After (`parse.py:96-104`):

```python
@dataclass(frozen=True)
class SkipRecord:
    s3key: str
    doc_id: str
    reason: str
    # True for parse exceptions (possibly environmental, retry next pass);
    # False for format-gate verdicts (a property of the key/bytes, terminal).
    retriable: bool = False
```

The format-gate path keeps the default `retriable=False` (`parse.py:203-206`), while the parse-exception handler sets it `True` (`parse.py:207-219`):

```python
    except Exception as exc:  # noqa: BLE001 — every failure must reach the ledger
        return SkipRecord(
            s3key=s3key,
            doc_id=doc_id,
            reason=f"{gate} parse failed: {exc}",
            retriable=True,
        )
```

### 2. Route retriable skips to a visible, re-runnable ledger state

The ingest loop now branches on `retriable` and records failures with `status="failed"` and **no checksum** (`ingest.py:144-155`):

```python
        if isinstance(result, parse.SkipRecord):
            if result.retriable:
                # Parse exceptions may be environmental (parser bug, memory
                # pressure), not a property of the bytes — record without a
                # checksum so the next pass retries, and count as failed.
                store.record_skip(result, status="failed")
                report["failed"] += 1
                report["failures"].append({"key": key, "reason": result.reason})
            else:
                store.record_skip(result, checksum)
                report["skipped"] += 1
            continue
```

Fetch failures got the same treatment — previously `store.record_skip(skip)` (a `skipped` row), now `store.record_skip(skip, status="failed")` counted as failed (`ingest.py:123-134`).

The retry itself is an emergent property of `needs_ingest`, which only treats a row as terminal when it is `complete`/`skipped` **and** its stored checksum matches the current pass's checksum (`store.py:286-300`):

```python
        return not (
            row["status"] in ("complete", "skipped")
            and checksum
            and row["checksum"] == checksum
        )
```

A `failed` row is never terminal (status doesn't match), and because it was written with an empty checksum, even the string comparison can't accidentally match a real `etag:`/content checksum on the next pass — so failed documents re-run every pass. Deliberate gate skips keep their checksum and stay terminal, exactly as designed (`record_skip` defaults `checksum=""`, `status="skipped"`, `store.py:336-348`).

### 3. Reconcile orphaned rows from crashed first-seen ingests

`run_ingest` now reconciles at pass start, reusing the ledger snapshot the resume path already loads (`ingest.py:81-87`):

```python
    ledger = store.ledger_snapshot()
    reconciled = store.reconcile_orphans(ledger)
```

The new method does one `doc_id` column scan per content table and deletes any row whose `doc_id` never reached the ledger (`store.py:265-284`):

```python
    def reconcile_orphans(self, ledger: dict[str, dict]) -> int:
        orphans: set[str] = set()
        for name in ("documents", "pages", "chunks", "assets"):
            table = self.table(name)
            count = table.count_rows()
            if count == 0:
                continue
            rows = table.search().select(["doc_id"]).limit(count).to_list()
            orphans.update(r["doc_id"] for r in rows if r["doc_id"] not in ledger)
        for doc_id in orphans:
            self._delete_document_rows(doc_id)
        return len(orphans)
```

This is a deliberate alternative to reintroducing a per-document pre-insert delete — that delete was removed precisely because, at Westlake scale, a `delete()` across all 5 tables per document (`_delete_document_rows`, `store.py:350-353`) was a table commit each, and the accumulated dead versions cost ~1.9–2 GB of ledger manifests at ~2,500 docs (`store.py:305-308`). One column scan at pass start restores crash-safety for first-seen docs without bringing the delete storm back. It is safe under the store's single-writer invariant (`store.py:26-29`): no other writer touches the tables during the scan-and-delete.

### 4. Also in the same cycle: the batch cap counts all real work

The `--max-new` batch cap was only evaluated after a successful upsert, so a run of consecutive skips or failures could overshoot it. The check moved to the top of the loop, counting all real work (`complete + skipped + failed`) before starting each document (`ingest.py:98-108`), which also makes `--max-new 0` a true no-op.

### One-time production remediation

The fix stops the bleeding for future passes but does not retroactively re-open the 9 rows already written as terminal `skipped` before the fix shipped. Per this session's remediation, those 9 pre-fix ledger rows were re-opened by clearing their stored checksums (making them non-terminal under `needs_ingest`) and retried via a targeted 9-document manifest. Outcome: the 4 clipboard-paste junk files now fail cheaply and visibly on every pass (correct terminal-but-counted behavior); the 5 oversized TIFF scans remain blocked pending a decision on Pillow's pixel cap (`Image.MAX_IMAGE_PIXELS`), since they are real evidence documents that the decompression-bomb guard legitimately refuses. The production store was also verified to have 0 orphans and 0 duplicates before the reconcile fix shipped — the 2026-07-08 SIGTERM happened to miss the crash window.

## Why This Works

The root cause was a **type that encoded two orthogonal concepts in one shape**. `SkipRecord` meant both "deliberately not ingestable" (a property of the key or bytes) and "this attempt errored" (a property of the run). Which one you got was disambiguated only by *what arguments the call site happened to pass* to `record_skip` — a real checksum plus the default `skipped` status made it terminal; the same call with no checksum plus `failed` made it retriable. Terminality was therefore an **emergent property of call-site argument choices**, not an explicit field anyone had to set and reviewers could see. The parse-exception path passed the content checksum simply because that was the variable in scope, and that incidental choice silently promoted every parse failure to permanent-and-invisible. Adding `retriable` turns terminality into a decision the code states out loud, checked at exactly one place (`needs_ingest`).

The crash-safety hole had a parallel shape. The ledger-last write order (`store.py:11-13`) guarantees that an interrupted document has no `complete` ledger row, so it re-runs cleanly — but that guarantee only held for **re-ingests**, where the pre-insert delete wipes the prior partial rows first. When the delete-storm optimization made first-seen docs skip that delete (`upsert_document`, `store.py:320-322`), it quietly removed the cleanup step that ledger-last safety implicitly depended on. A crash between `_insert_rows` and `_write_ledger` then left content rows with no ledger row; the rerun sees `prior is None`, skips the delete again, and inserts a second copy. `reconcile_orphans` restores the invariant that content rows and ledger rows agree, by making "no ledger row" mean "delete these rows" at pass start.

## Prevention

- **Failure-path taxonomy.** Every error path must land in a ledger state that is *both* visible (counted as a failure, surfaced in the report) *and* retriable, unless the failure is provably a permanent property of the input. Terminality must be an explicit, named decision (`SkipRecord.retriable`), never an accident of which arguments a call site passed.
- **Don't bucket errors with deliberate no-ops.** A metric that sums genuine failures together with intentional skips is structurally blind — the larger deliberate count (here ~5,100 gate skips) drowns the signal you actually care about. Count deliberate skips and real failures in separate report fields (`skipped` vs `failed`), as the loop now does.
- **Contract tests for retry and crash semantics.** Three new tests lock the behavior in: `test_parse_failure_counts_failed_and_retries` asserts a parse exception is counted `failed` with an empty checksum and then completes on a second pass; `test_crashed_first_ingest_reconciles_without_duplicates` simulates a crash between `_insert_rows` and the ledger write and asserts the rerun reconciles rather than duplicates; `test_max_new_counts_skips_toward_cap` guards the related batch-cap fix (all in `agents/doc-intel/analysts/tests/test_evidence_store.py`).
- **Cross-provider adversarial review before merge.** The blind spot was invisible to author-aligned review precisely because that review shared the author's mental model of how the code was supposed to behave. A reviewer from a different provider (Codex), with no stake in the original design, read what the code actually did — and three independent reviewers converged on the crash-window defect. Route agent-written diffs through a model that did not write them.

## Related Issues

- [PR #12](https://github.com/Formentera-Operations/eve-agents/pull/12) — the merged PR carrying both fixes (memory-bounded resumable ingest at Westlake scale).
- [Issue #13](https://github.com/Formentera-Operations/eve-agents/issues/13) — the known second-order consequence of making failures retriable: a `--max-new` batch whose cap fills entirely with the same contiguous persistent failures makes zero forward progress past them.
- `references/evidence-store.md` — evidence-store architecture, including the ledger table schema and resumable-ingest contract this fix corrected.
- `decisions/2026-07-09-evidence-store-migration.md` — the migration decision whose "0 failures" figure predates this fix and reflects the blind metric.
