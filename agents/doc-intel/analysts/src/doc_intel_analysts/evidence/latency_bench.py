"""Evidence-store latency benchmark: time retrieval ops against lance roots.

The instrument behind ``benchmark/results/2026-07-11-phase2-s3-latency.json``
(local NVMe vs direct S3), ported from the session scratchpad so the same
ops and row shape (``op`` / ``cold_s`` / ``warm_median_s`` /
``within_60s_tool_budget``) gate the in-Azure NFS mount next. Roots are
parameterized: pass ``--root`` repeatedly for A/B comparison.

Read-only by construction: roots are opened via ``lancedb.connect`` +
``open_table`` only — never ``EvidenceStore``, whose ``__init__`` creates
missing tables and would mutate a real store root. The query embedding is a
sampled stored chunk vector, so no gateway credential is needed.

Every call is capped (default 90s) by submitting to a single-thread executor
and abandoning the future on timeout; a call that raises instead records an
``ERROR: <ExcType>`` row and the run continues. Fixture sampling runs under
the same cap but fails the whole run (``FixtureSamplingError``, nonzero CLI
exit) — without fixtures there are no results to save. Abandoned threads are
non-daemon and a stuck read (observed against direct S3) would block a normal
interpreter exit, so the CLI finishes with ``os._exit`` after results are on
disk; the library entry points return normally.

Run from the analysts directory:

    uv run python -m doc_intel_analysts.evidence.latency_bench \
        --root .evidence/lance --root s3://bucket/prefix/lance \
        --out results.json
"""

import argparse
import json
import logging
import os
import statistics
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any

from doc_intel_analysts.evidence.retrieval import EvidenceRetriever

DEFAULT_CAP_S = 90.0
TOOL_BUDGET_S = 60.0

log = logging.getLogger("doc-intel-analysts")


class FixtureSamplingError(RuntimeError):
    """Fixture sampling from the first root timed out or raised.

    Raised before any op is benched — there are no results to persist, so
    the CLI exits nonzero instead of writing ``--out``.
    """


class ReadOnlyStore:
    """Read-only stand-in for EvidenceStore: ``table()`` over ``open_table``.

    Never point EvidenceStore at a root under measurement — its ``__init__``
    creates any missing tables, mutating the store.
    """

    def __init__(self, uri: str) -> None:
        import lancedb

        self._db = lancedb.connect(uri)
        self._tables: dict[str, Any] = {}

    def table(self, name: str) -> Any:
        if name not in self._tables:
            self._tables[name] = self._db.open_table(name)
        return self._tables[name]


def timed(
    fn: Callable[[], object], cap: float = DEFAULT_CAP_S
) -> float | Exception | None:
    """Wall-clock one call; None if it exceeds ``cap`` seconds, the raised
    exception if the call fails instead of finishing.

    The future is abandoned on timeout (``shutdown(wait=False)``) so a stuck
    read cannot stall the run; the thread may linger (see module docstring).
    """
    executor = ThreadPoolExecutor(max_workers=1)
    start = time.perf_counter()
    future = executor.submit(fn)
    try:
        future.result(timeout=cap)
        elapsed = time.perf_counter() - start
        executor.shutdown(wait=False)
        return elapsed
    except FutureTimeout:
        executor.shutdown(wait=False)
        return None
    except Exception as exc:
        executor.shutdown(wait=False)
        log.warning("benched call raised %s: %s", type(exc).__name__, exc)
        return exc


def sample_fixtures(store: ReadOnlyStore) -> tuple[list[float], str, str]:
    """Sample a stored chunk vector (the query embedding — no gateway) plus
    a screenshot-bearing page id and its doc id."""
    chunk = store.table("chunks").search().select(["vector"]).limit(1).to_list()[0]
    page = (
        store.table("pages")
        .search()
        .where("has_screenshot = true")
        .select(["page_id", "doc_id"])
        .limit(1)
        .to_list()[0]
    )
    return list(chunk["vector"]), page["page_id"], page["doc_id"]


def _timeout_sentinel(cap: float) -> str:
    return f">{cap:g} TIMEOUT"


def _error_sentinel(exc: Exception) -> str:
    return f"ERROR: {type(exc).__name__}"


def _failure_sentinel(outcome: float | Exception | None, cap: float) -> str | None:
    """Sentinel string when a ``timed`` outcome failed; None when it succeeded."""
    if outcome is None:
        return _timeout_sentinel(cap)
    if isinstance(outcome, Exception):
        return _error_sentinel(outcome)
    return None


def _bench_op(
    name: str, fn: Callable[[], object], warm_passes: int, cap: float
) -> dict:
    """One result row: cold pass, then warm passes (skipped after a cold
    timeout or error; a warm timeout or error discards that op's warm
    numbers). Failures never propagate — the row carries the sentinel and
    the run moves on to the next op."""
    cold = timed(fn, cap)
    failure = _failure_sentinel(cold, cap)
    warms: list[float] = []
    if failure is None:
        for _ in range(warm_passes):
            warm_run = timed(fn, cap)
            failure = _failure_sentinel(warm_run, cap)
            if failure is not None:
                warms = []
                break
            warms.append(warm_run)
    warm_median = statistics.median(warms) if warms else None
    return {
        "op": name,
        "cold_s": round(cold, 3) if isinstance(cold, float) else failure,
        "warm_median_s": (
            round(warm_median, 3) if warm_median is not None else failure
        ),
        "within_60s_tool_budget": (
            isinstance(cold, float)
            and cold <= TOOL_BUDGET_S
            and failure is None
            and (warm_median is None or warm_median <= TOOL_BUDGET_S)
        ),
    }


def bench_root(
    uri: str,
    query_vector: list[float],
    page_id: str,
    doc_id: str,
    *,
    cap: float = DEFAULT_CAP_S,
    warm: int = 3,
    scan_heavy_warm: int = 1,
) -> list[dict]:
    """Run the 10 baseline ops against one root; rows match the committed
    S3-vs-local baseline so runs compare directly."""
    store = ReadOnlyStore(uri)
    retriever = EvidenceRetriever(
        store, query_embedder=lambda texts: [query_vector for _ in texts]
    )
    ops: list[tuple[str, Callable[[], object], int]] = [
        (
            "open+count(4 tables)",
            lambda: [
                store.table(name).count_rows()
                for name in ("chunks", "pages", "documents", "ledger")
            ],
            warm,
        ),
        (
            "vector search (chunks, hybrid leg)",
            lambda: retriever.search(
                "stuck pipe casing problems while drilling", mode="chunks", limit=5
            ),
            warm,
        ),
        (
            "fts search (chunks)",
            lambda: retriever.search("stuck pipe", mode="fts", limit=5),
            warm,
        ),
        (
            "grep exact 'S733H' (pages scan)",
            lambda: retriever.grep("S733H", limit=20),
            scan_heavy_warm,
        ),
        (
            "grep filtered '9,020' (Westlake)",
            lambda: retriever.grep("9,020", limit=20, asset_team="WESTLAKE RESOURCES"),
            scan_heavy_warm,
        ),
        (
            "find_documents 'surveys'",
            lambda: retriever.find_documents("surveys", limit=25),
            warm,
        ),
        (
            "document_status '.xlsx' skipped",
            lambda: retriever.document_status(
                name_query=".xlsx", status="skipped", limit=25
            ),
            warm,
        ),
        ("get_page (text)", lambda: retriever.get_page(page_id), warm),
        (
            "get_page (+screenshot blob)",
            lambda: retriever.get_page(page_id, include_screenshot=True),
            warm,
        ),
        ("get_document_pages", lambda: retriever.get_document_pages(doc_id), warm),
    ]

    rows = []
    for name, fn, warm_passes in ops:
        row = _bench_op(name, fn, warm_passes, cap)
        rows.append(row)
        log.info(
            "[%s] %s: cold=%s warm=%s",
            uri,
            name,
            row["cold_s"],
            row["warm_median_s"],
        )
    return rows


def run_latency_bench(
    roots: Sequence[str],
    *,
    cap: float = DEFAULT_CAP_S,
    warm: int = 3,
    scan_heavy_warm: int = 1,
) -> dict:
    """Bench every root with identical ops and fixtures.

    Fixtures (query vector + page/doc ids) are sampled from the FIRST root,
    so list the cheapest root (local) first. Sampling is capped like every
    benched call and raises ``FixtureSamplingError`` on timeout or failure —
    with no fixtures there is nothing to bench. Returns normally — CLI-only
    hard-exit behavior lives in ``main``.
    """
    # sample_fixtures does blocking store reads; run it under the same cap so
    # an unresponsive first root fails loud instead of hanging the run.
    sampled: list[tuple[list[float], str, str]] = []
    outcome = timed(
        lambda: sampled.append(sample_fixtures(ReadOnlyStore(roots[0]))), cap
    )
    if outcome is None:
        raise FixtureSamplingError(
            f"fixture sampling exceeded {cap:g}s — "
            f"root unresponsive or unreadable: {roots[0]}"
        )
    if isinstance(outcome, Exception):
        raise FixtureSamplingError(
            f"fixture sampling failed ({type(outcome).__name__}: {outcome}) — "
            f"root unresponsive or unreadable: {roots[0]}"
        ) from outcome
    query_vector, page_id, doc_id = sampled[0]
    log.info(
        "fixtures: page_id=%s doc_id=%s vec_dims=%d", page_id, doc_id, len(query_vector)
    )
    return {
        "fixtures": {"page_id": page_id, "doc_id": doc_id},
        "roots": {
            root: bench_root(
                root,
                query_vector,
                page_id,
                doc_id,
                cap=cap,
                warm=warm,
                scan_heavy_warm=scan_heavy_warm,
            )
            for root in roots
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evidence-store latency benchmark")
    parser.add_argument(
        "--root",
        action="append",
        required=True,
        dest="roots",
        help="lance root URI (repeat for A/B; fixtures sample from the first)",
    )
    parser.add_argument("--out", type=Path, required=True, help="JSON results path")
    parser.add_argument(
        "--cap", type=float, default=DEFAULT_CAP_S, help="per-op timeout in seconds"
    )
    parser.add_argument("--warm", type=int, default=3, help="warm passes per op")
    parser.add_argument(
        "--scan-heavy-warm", type=int, default=1, help="warm passes for grep ops"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Direct-S3 roots need a region even when no other AWS config is present.
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

    try:
        results = run_latency_bench(
            args.roots,
            cap=args.cap,
            warm=args.warm,
            scan_heavy_warm=args.scan_heavy_warm,
        )
    except FixtureSamplingError as err:
        log.error("%s", err)
        # No results exist yet, and the abandoned sampling thread is
        # non-daemon and would block a normal interpreter exit — hard-exit
        # nonzero so the gate run fails loud.
        os._exit(1)
    args.out.write_text(json.dumps(results, indent=1))
    print(f"results written: {args.out}")
    # Abandoned timeout threads are non-daemon and would block a normal
    # interpreter exit; results are already on disk, so hard-exit.
    os._exit(0)


if __name__ == "__main__":
    main()
