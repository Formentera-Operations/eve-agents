# Ontology individuals enrichment — U4 gate results (2026-07-06)

Plan: `docs/plans/2026-07-06-001-feat-ontology-individuals-plan.md`

## Generation (U1–U3)

- 484 verified individuals emitted into `references/ontology/welldrive.owl`
  (415 Well, 35 ServiceVendor, 16 County, 15 Operator, 3 AssetTeam);
  198 candidates unverified (visible in the gitignored report).
- Ontology grew 243 → 1,695 triples; parse + determinism + round-trip tests green.
- Preflight simulation (cognee's exact matcher, offline): 531/4,720 entities
  predicted ontology_valid before spending the rebuild.

## First rebuild + bar revision

First rebuild (484 loose individuals): 278/4,222 valid — under the original
≥400 bar. Spot-check exposed fuzzy false positives ('dwayne' → Wayne County
at difflib 0.909; 'three forks' formation → vendor via prefix; 'south texas'
region → operator). Tightened per the precision gate (short keys exact-only,
counties exact-only, org-prefix only on organization-typed candidates) and
regenerated: 415 individuals. An offline simulator running cognee's exact
matcher reproduced the measured run exactly (278 predicted / 278 measured)
and forecast ~263 for the tightened set — the corpus's honest matchable
population is ~270–320 (most entities are dates/depths/measurements that can
never match). **Rob revised the bar 400 → 250 (2026-07-06).**

## Final rebuild gates (revised bar: ≥250 valid; ≥90% precision; evals 4/4)

- ontology_valid: **PASS — 259/4,359 entities (21.6× the 12 baseline)**;
  by class: 211 Well, 17 ServiceVendor, 14 Operator, 14 County, 3 AssetTeam
- 20-node precision spot-check: **PASS — 20/20 correct (100%)**, stratified
  across all five classes; every matched individual is the document's entity
- Evals: **PASS — graph-explore 4/4, delegation 4/4** (8/8 gates, 1m34s)
- Rebuilds: cognify 242.5s + 230.2s, 311/311 docs ok both runs; cost per AI
  Gateway dashboard delta (two full ingests, same order as the ~$2 baseline
  run each)
- Final graph: 6,511 nodes / 26,652 edges; exports refreshed at
  `runs/doc-intel/graph/`
