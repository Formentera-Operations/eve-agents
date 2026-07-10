---
title: "Graph export wrote kuzu storage-table names as edge labels — poisoning edges.csv and silently shrinking the ontology"
date: 2026-07-10
category: integration-issues
module: doc-intel analysts graph export and ontology individuals (cognee integration)
problem_type: integration_issue
component: assistant
symptoms:
  - "edges.csv label column carried kuzu storage-table names instead of semantic relationships — 4,232 of 5,156 is_a edges (82%) mislabeled in the 2026-07 export"
  - "SQL consumers joining on label per references/graph-export.md silently got wrong answers"
  - "Ontology-individuals typed candidate pools starved (extract_candidates filtered label != 'is_a'); entities fell to the catch-all sweep where org-prefix is disabled and misses drop silently"
  - "Previously verified individuals (liberty_energy ontology_valid=true in the July 6 graph) silently fell out of the ontology on later regenerations"
  - "No instrument caught it — the graph-explore eval never touches the CSVs and the unverified-report only shows typed-pool misses"
root_cause: wrong_api
resolution_type: code_fix
severity: high
tags: [cognee, kuzu, knowledge-graph, graph-export, edge-labels, relationship-name, ontology-individuals, silent-data-corruption]
---

# Graph export wrote kuzu storage-table names as edge labels — poisoning edges.csv and silently shrinking the ontology

## Problem

cognee's `get_graph_data()` returns edge tuples whose label element is the **kuzu storage-table name** — cognee packs many relationship types into shared tables — while the true semantic relationship lives in `properties.relationship_name`. The graph exporter wrote that tuple label straight into `edges.csv`, so on the 2026-07 export 4,232 of 5,156 `is_a` edges (82%) carried a wrong label (per the PR #19 measurement; the divergence is now documented at `agents/doc-intel/analysts/src/doc_intel_analysts/graph/export.py:41-45`). Two consumers inherited the corruption: every SQL consumer of the open `edges.csv` data product, and the ontology-individuals generator — whose typed candidate pools starved, causing previously verified vendors to silently fall out of `references/ontology/welldrive.owl` on each regeneration. The ontology was quietly shrinking.

## Symptoms

- During the ontology-individuals regeneration for Bull Mountain pilot step 1, key vendors (`liberty`, `halliburton`, `nabors`) were **neither verified as individuals nor present in the unverified report** — a double absence that the generator's design contract says should be impossible ("the generator reports them so misses are visible rather than silent" — R4 in `docs/plans/2026-07-06-001-feat-ontology-individuals-plan.md:51`).
- The ontology was shrinking across regenerations, not just failing to grow: `liberty_energy` had been a live match in production (`ontology_valid: true` in the July 6 graph export, per PR #19) yet was absent from the committed `welldrive.owl`.
- An `is_a` edge whose `properties` said `relationship_name: "is_a"` with edge text "liberty oilfield services is a company." carried the label `turned_to_sales` in `edges.csv` (per this session's inspection of the corrupted export; the label pairing is preserved in the regression test at `agents/doc-intel/analysts/tests/test_export.py:36-40`, and the divergence itself is documented in the comment at `export.py:41-45`).
- `edges.csv` is the open data product — `references/graph-export.md:41-48`'s worked example joins on `e.label` (`where e.label = 'performed_on'`), so every downstream SQL consumer inherited wrong answers with no error.

## What Didn't Work

- **First hypothesis: a fuzzy-matching distance failure.** The obvious theory was that `liberty` vs `LIBERTY ENERGY SERVICES LLC` fell below the difflib 0.9 verification cutoff (`individuals.py:148`). Wrong layer entirely — the entities never became candidates at all, so no string metric was ever consulted. Chasing match scores would have led to loosening a cutoff that was working as designed.
- **The kuzu native `relationship_name` column as the repair source.** The fallback path's Cypher can read a native `e.relationship_name` column, which looked like the obvious authoritative source. But it disagrees with the `properties` JSON on thousands of edges (per this session's measurement: 1,823 vs 5,352 `is_a` edges; the code records "it disagrees with the native relationship_name column on thousands of edges" at `export.py:54-56`). The `properties` JSON column is what the engine itself deserializes and it matched the known-good liberty ground-truth edge — so it, not the native column, is authoritative.
- **Trusting that the kuzu fallback existed at all.** A Codex review of PR #19 discovered the pre-existing fallback was dead code on the current stack, for three independent reasons (recorded in PR #19's fallback-rebuild commit message and verifiable in the current tree): `label(e)` returns literally `'EDGE'` because cognee keeps one shared rel table (handled at `export.py:65-69`); `get_as_df()` crashes on STRUCT ids under ladybug 0.17.1 (observed in this session as an `UNREACHABLE_CODE` assertion failure) — the installed `kuzu` package is now a compatibility shim over ladybug (`.venv/.../site-packages/kuzu/__init__.py`: "Compatibility shim exposing Ladybug under the legacy Kuzu module name"; ladybug 0.17.1 pinned in `agents/doc-intel/analysts/uv.lock`) — hence the row iterator workaround at `export.py:73-75`; and the `*.kuzu` glob never matched the actual store file, which is named `cognee_graph_kuzu` with no extension (`export.py:101-107`).

Why none of the existing defenses caught it:

- **Three per-edge label channels exist and they disagree** — the engine tuple label (storage-table name), the kuzu native `relationship_name` column, and the serialized `properties` JSON. Nothing asserted they agreed, so each consumer silently picked one.
- **The `graph-explore` eval kept passing** (`agents/doc-intel/evals/graph-explore.eval.ts`) because cognee's internal search answers from its own engine state and never reads the exported CSVs. The eval verified the graph; the corruption lived only in the export.
- **The unverified report only covers typed-pool candidates** (`individuals.py:291-305`). Entities that lose their typing fall to the catch-all sweep, where misses are silent *by design* — sweep names "never enter the unverified report (that would drown real misses)" (`individuals.py:310-311`). The label corruption pushed real vendors into exactly the pool whose misses are invisible.

## Solution

Shipped in **PR #19** (merged 2026-07-09), in four parts — the label fix, generator tolerance for cached exports, the alias layer, and the fallback rebuild — plus regression tests and the regenerated individuals.

### 1. Export the semantic label, not the storage-table name

`rows_from_graph` now prefers `properties.relationship_name` for the CSV `label`, keeping it in props so existing consumers that read it there don't break (`export.py:36-47`):

```python
    for edge in edges:
        source, target = edge[0], edge[1]
        label = edge[2] if len(edge) > 2 else ""
        props = (edge[3] if len(edge) > 3 else {}) or {}
        # The engine tuple's label is the storage-table name — cognee packs
        # many relationship types into shared tables, so it diverges from the
        # semantic relationship (82% of is_a edges on the 2026-07 export).
        # properties.relationship_name is authoritative; keep it in props so
        # existing consumers reading it there don't break.
        label = props.get("relationship_name") or label
```

### 2. Make the generator tolerant of cached pre-fix exports

Pre-fix, `extract_candidates` filtered edges with `if row["label"] != "is_a": continue` (line 87 of `individuals.py` at PR #19's base) — trusting the corrupted column. The current tree routes every edge through `_edge_relationship`, which prefers the `properties` JSON and falls back to `label`, so cached pre-fix exports still yield candidates (`individuals.py:55-65`, used at `individuals.py:100-101`):

```python
def _edge_relationship(row: dict[str, str]) -> str:
    """Exports written before the export.py label fix carry the storage-table
    name in `label`; the semantic relationship lives in properties. Prefer
    properties so cached pre-fix exports still yield candidates."""
```

### 3. Alias layer for misses no string metric can bridge

Healing the labels recovered typing but exposed a residual class of misses: corporate renames and brands that bill through a parent ("liberty oilfield services" renamed to Liberty Energy in 2022; Baroid is a Halliburton product service line). PR #19 added a hand-curated alias table, `references/ontology/aliases.csv`, loaded by `load_aliases` (`individuals.py:127-141`); aliases short-circuit all matching — sweep included — and fail loud on a master typo (`individuals.py:263-274`).

### 4. Rebuild the dead kuzu fallback around the authoritative channel

`kuzu_fallback_edge` reassembles fallback edges from the `properties` JSON column — "what the engine deserializes" — with the native column and the shared `'EDGE'` table name as successively weaker fallbacks (`export.py:51-70`); `_iter_rows` iterates the query result directly instead of the crashing `get_as_df` (`export.py:73-75`); store discovery matches kuzu-named files without assuming an extension (`export.py:101-107`); and the database opens `read_only` (`export.py:110`).

### 5. Regression tests in both directions

- `agents/doc-intel/analysts/tests/test_export.py:32-42` — the CSV label prefers `properties.relationship_name` over the tuple label, and `relationship_name` stays in props.
- `agents/doc-intel/analysts/tests/test_export.py:45-55` — `kuzu_fallback_edge` preference order: properties JSON, then native column, then table name; bad JSON tolerated.
- `agents/doc-intel/analysts/tests/test_individuals.py:80-90` — corrupted-label pooling: properties win in *both* directions (a `turned_to_sales` label with `is_a` properties pools; an `is_a` label with `performed_on` properties does not).

### Verification

- Fresh export: **5,352/5,352 `is_a` labels agree** between `label` and properties (was 924/5,156), per PR #19.
- The rebuilt fallback was proven live by **force-failing the primary path** (a `unittest.mock` patch of `get_graph_engine`, per this session's test): identical node/edge counts (6,567 / 26,832) and identical label distribution to the primary export, with full props on every edge — recorded in PR #19's fallback-rebuild commit message.
- The regeneration recovered **HALLIBURTON ENERGY SERVICE INC** and **NABORS DRILLING TECHNOLOGIES USA INC** as individuals (ServiceVendor 17→21), and the unverified report grew 108→319 rows — a feature, not a regression: misses that had been silent sweep drops became visible (PR #19).
- Downstream, the Bull Mountain pilot validated 293 ontology-valid entities of a measured matchable ceiling of 337 — **86.9%, with zero runtime matcher misses** (`decisions/2026-07-10-selective-graph-enrichment.md:24-25`).

## Why This Works

The root cause is a physical/semantic channel confusion. Kuzu's storage layer packs many relationship types into shared tables, so the "label" the engine tuple exposes is a *physical* artifact of table assignment, not the *semantic* relationship. The engine itself never trusts that field for meaning — it deserializes `properties.relationship_name`. The exporter consumed the physical channel and published it as if it were the semantic one, and once that was in `edges.csv` the corruption was indistinguishable from data: every value was a plausible-looking relationship name, just frequently the wrong one.

The blast radius was amplified by a chain of individually reasonable design decisions in `individuals.py`. Typing flows through `is_a` edges (`individuals.py:100-109`), so mislabeled `is_a` edges starve the typed candidate pools. Untyped names fall to the catch-all sweep (`individuals.py:117-122`), where two precision guards — each correct in isolation — turn starvation into silent loss: the org-prefix rule is deliberately disabled on sweep names because it used to turn formations and regions into vendors ("'three forks', 'south texas'", `individuals.py:283-287`; locked by `agents/doc-intel/analysts/tests/test_individuals.py:299-303`), and sweep misses never enter the unverified report because they would drown real misses (`individuals.py:310-311`). So a corrupted label didn't produce a visible failure; it *relocated* real vendors into the one pool engineered to fail quietly, inverting the R4 "misses are visible" contract without violating any single component's local logic.

The fix works because it re-points every consumer at the one channel the engine itself treats as authoritative: the exporter's primary path (`export.py:46`), the exporter's fallback path (`export.py:51-70`), and the generator's edge reader (`individuals.py:55-65`) all now read `properties.relationship_name` first. The weaker channels remain only as ordered fallbacks for rows where the authoritative one is absent, and regression tests pin the preference order at each layer.

## Prevention

- **When an engine exposes the same fact through multiple channels, find the one the engine itself consumes and treat only that as authoritative.** Here there were three (tuple label, native column, properties JSON) and they disagreed on thousands of edges. The tiebreaker was empirical: which channel does the engine deserialize, and which channel matches a known-good ground-truth edge. Encode the verdict in code comments at the read site (`export.py:41-45`, `export.py:52-57`) so the next reader doesn't re-litigate it.
- **Distribution-level assertions catch what per-row tests miss.** Every individual row of the corrupted export looked plausible; only the histogram was wrong. A `label`-vs-`properties.relationship_name` agreement count (the 5,352/5,352 verification query) detects this class of corruption in one line. `references/graph-export.md:52-53` already tells consumers to enumerate labels with `select label, count(*) from edges group by 1` — run that same shape as a producer-side check after export, not just as consumer documentation.
- **A data product needs at least one consumer-side integrity check.** `edges.csv` had exactly one real in-repo consumer (the individuals generator; SQL consumers exist only at the contract level) and that consumer failed silent. The corrupted product shipped for weeks because nothing downstream could tell healed data from poisoned data. The corrupted-label pooling test (`agents/doc-intel/analysts/tests/test_individuals.py:80-90`) now makes the generator itself assert the contract it depends on.
- **Force-fail the primary path to prove a fallback actually works.** The kuzu fallback had been dead for an unknown time — three independent defects, any one fatal — and nothing noticed because the primary path never failed. A fallback that has never executed against the real store is a hope, not a fallback. The live test (mock-patch `get_graph_engine` to raise, then require identical counts and label distribution to the primary) is cheap and should accompany any fallback path's introduction or rewrite.
- **Guarded pools need their own visibility story.** The sweep's "verify silently or drop" design was a deliberate precision trade-off, but it created a pool whose misses are invisible by construction. When a design includes an intentionally silent path, the invariant that keeps important items *out* of that path (here: typing via `is_a` edges) deserves an explicit check — otherwise upstream corruption converts visible misses into silent ones.
- **Cross-provider adversarial review, again.** As with the evidence-store ledger bug (PR #12), the decisive finding — the fallback was dead code — came from a Codex review of PR #19, not from the author-aligned pass that wrote it.

## Related Issues

- [PR #19](https://github.com/Formentera-Operations/eve-agents/pull/19) — the fix: export labels from `relationship_name`, alias layer, fallback rebuild, regenerated individuals (merged 2026-07-09).
- [PR #21](https://github.com/Formentera-Operations/eve-agents/pull/21) — `graph.ingest --from-evidence`, the enrichment path whose pilot run depended on the healed export (merged 2026-07-09).
- [PR #22](https://github.com/Formentera-Operations/eve-agents/pull/22) — individuals pass 2: pilot-graph candidates + confirmed IPT alias (open at time of writing).
- `references/graph-export.md` — the open data product contract, including the `e.label` worked example that made the corruption consumer-facing.
- `docs/plans/2026-07-06-001-feat-ontology-individuals-plan.md` — the R4 "misses are visible rather than silent" contract this bug inverted.
- `decisions/2026-07-10-selective-graph-enrichment.md` — pilot close-out recording the post-fix 86.9%-of-ceiling / zero-matcher-miss result.
- `docs/solutions/logic-errors/ingest-ledger-conflates-parse-failures-with-skips.md` — sibling learning: a different silent-failure bug in the same subsystem, also surfaced by cross-provider review.
