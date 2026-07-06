---
title: "Cognee ontology-individuals matching: URI fragments are the whole surface, and '#' corrupts them"
date: 2026-07-06
category: integration-issues
module: doc-intel analysts ontology individuals (cognee integration)
problem_type: integration_issue
component: assistant
symptoms:
  - "Class-only OWL matched 12/4,720 extracted entities — cognee matches individuals, not classes"
  - "URI fragment containing '#' collapses the resolver key to its tail ('#winston_gatlin_#3h' resolves to key '3h'); 23 well individuals became garbage lookup entries"
  - "Fuzzy verification at 0.9 false-positives on short names ('dwayne' matched county 'wayne' at 0.909)"
  - "Prefix matching on untyped candidates typed formations and regions as vendors ('three forks', 'south texas')"
  - "Entity extraction is non-deterministic run-to-run (4,222/4,449/4,720 entities across three identical ingests)"
root_cause: logic_error
resolution_type: code_fix
severity: high
tags: [cognee, ontology-matching, individuals, uri-fragments, rdflibontologyresolver, fuzzy-matching, entity-extraction, non-determinism]
related_components: [database]
---

# Cognee ontology-individuals matching: URI fragments are the whole surface, and '#' corrupts them

## Problem

The doc-intel graph enriches extracted entities by matching them against a
welldrive OWL ontology loaded into cognee 1.2.2. With a class-only ontology
(OWL `owl:Class` declarations, no instances), only **12 of 4,720** extracted
entities came back `ontology_valid` — there was nothing for entity names to
match against. The goal was to make cognee type real-world entities (wells,
operators, service vendors, counties) by minting **named individuals** into
the OWL, verified against Snowflake masters so precision stayed high.

The work landed at **276 / 4,449** valid entities from **415 individuals**,
100% precision on spot-check, evals 4/4 (PRs #8/#9, merged 2026-07-06). Getting
there meant reverse-engineering how cognee's resolver actually matches text to
individuals — a process with several non-obvious traps that silently produce
either zero matches or confidently wrong ones.

## Symptoms

- Class-only ontology: 12/4,720 valid. Adding classes alone moved nothing —
  cognee matches entities to *individuals*, and there were none.
- `rdfs:label` aliases would have had no effect — labels are never consulted
  (rejected at design time after reading the resolver source).
- A first individuals set (484 individuals) produced **278 matches but with
  class errors** in spot-check: formations and regions typed as vendors,
  short person-names typed as counties.
- 23 individuals minted from well names collapsed to garbage keys like `3h`
  that exact-matched unrelated junk entities — and the round-trip unit test
  stayed green through it.
- Match counts drifted run-to-run (4,222 / 4,449 / 4,720 entities across three
  ingests of the *same* 311 documents), so a fixed success bar kept moving.

## What Didn't Work

**(a) Class-only OWL.** Declaring `Well`, `Operator`, etc. as `owl:Class` gave
the resolver a `classes` lookup but an empty `individuals` lookup. Entity
extraction produces instance names ("WINSTON GATLIN #3H"), which match against
individuals, not class names. Result: 12 valid, and those 12 were entities
whose names happened to equal a class key.

**(b) `rdfs:label` aliases.** The intuition was to attach alternate spellings
as labels. Reading the resolver source killed it before implementation:
`build_lookup` keys the `individuals` dict purely by URI local name via
`_uri_to_key`, and `find_closest_match` normalizes the incoming entity name
the same way. `label` is never read. Aliases-as-labels silently do nothing.

**(c) Fuzzy/prefix false positives in the first individuals set.** The
generator's verification pass ran difflib at 0.9 — which still admits
near-miss short names — plus an org-name prefix rule applied to *all*
candidates. `dwayne` matched county `wayne` (0.909); `three forks` (a
formation) and `south texas` (a region) prefix-matched vendor names. The first
rebuild hit 278 matches but with those class errors in the sample.

**(d) A round-trip test that masked key collapse.** The property test
normalized *both* sides with the project's own `normalize_key`, then asserted
the fragment survived `_uri_to_key`. It did survive — as the garbage tail. The
test asserted a fixed point that the corruption also satisfied, so it never
caught the `#` collapse. Codex's PR review caught it, not the suite.

## Solution

Read the resolver source and mint **verified named individuals** whose URI
fragments are shaped for exactly how cognee derives match keys.

**Match on the fragment, because that's all cognee sees.** The resolver's
`_uri_to_key` is the whole matching surface:

```python
def _uri_to_key(self, uri: URIRef) -> str:
    uri_str = str(uri)
    if "#" in uri_str:
        name = uri_str.split("#")[-1]
    else:
        name = uri_str.rstrip("/").split("/")[-1]
    return name.lower().replace(" ", "_").strip()
```

Runtime matching is exact-first, then `difflib.get_close_matches(..., cutoff=0.8)`
(`FuzzyMatchingStrategy`). The generator's `normalize_key` is kept
byte-identical to that normalization so minted fragments hit the exact path.

**Strip `#` from fragments before minting.** A well like `WINSTON GATLIN #3H`
normalizes to `winston_gatlin_#3h`; because `_uri_to_key` splits on `#`, the
lookup key collapses to `3h`. `fragment_key` removes `#` up front:

```python
def fragment_key(name: str) -> str:
    return normalize_key(name).replace("#", "")
```

Stripping costs the exact hit for `#`-spelled names, but the 0.8 runtime fuzzy
still reaches them at ~0.97 similarity.

**Verify against per-class Snowflake masters, stricter than runtime.** The
generator matches candidates to `WELL_NAME`, `COMPANY_NAME`, `VENDOR_NAME`,
`COUNTY` masters at cutoff **0.9**, with guards that killed the (c) false
positives: keys under 8 characters are exact-only (blocks `dwayne`→`wayne`),
counties are exact-only at any length, and org-prefix matching is restricted to
organization-typed candidates (blocks `three forks`).

The guards do **not** cover exact master hits: `south texas` survives as an
`Operator` individual because the well master literally carries
`COMPANY_NAME = "South Texas"` on one row, and exact matching runs before
every guard. Exact collisions between region/formation words and dirty
master name values are a residual precision limit bounded by master data
quality — the spot-check is the detector, not the guards.

```python
if not fuzzy or len(candidate_key) < 8:
    return None
close = difflib.get_close_matches(candidate_key, list(lookup), n=1, cutoff=VERIFY_CUTOFF)
```

**Gate every paid rebuild with an offline matcher simulation.** Before spending
~$2 and ~5 min on a real ingest, reimplement cognee's exact algorithm
(normalize + exact + difflib 0.8) over the current export's entity names vs the
candidate individual keys. This predicted the rebuild result **exactly** —
278 predicted, 278 measured on the same population — so it doubles as a
pre-flight gate and as an honest ceiling measurement.

## Why This Works

cognee's individual matching has exactly one input — the URI local name after
`#` — and one algorithm — normalize, exact, then difflib at 0.8, over a
**global** individuals lookup (any entity can match any individual, class is not
scoped at match time). Once that's the ground truth, three things follow:

- Fragments must *be* the match keys, so shaping them (`fragment_key`,
  identical `normalize_key`) is the whole game; labels and class scoping are
  noise.
- Precision is controlled entirely by *what enters the OWL*. The runtime cutoff
  is fixed at 0.8, so the only lever is a stricter generator (0.9 + short-key
  and typed-candidate guards). Keep bad individuals out and bad matches can't
  happen.
- Because the offline simulator runs the identical algorithm over the identical
  population, its prediction is the measurement. It let the team revise the
  success bar from 400 down to a defensible 250 (the corpus's real matchable
  ceiling is ~270–320 of ~4,400 — most entities are dates, depths, and
  measurements that can never match a named individual).

## Prevention

- **Read the resolver before shaping data for it.** The `label` dead-end and
  the `#` collapse were both visible in ~10 lines of `_uri_to_key` /
  `build_lookup`. Grepping the installed package beats guessing from docs.
- **Never put `#` (or any `_uri_to_key` delimiter) inside a minted fragment.**
  Well numbers, API suffixes, and lease designators are the usual carriers.
- **Test against the consumer's algorithm, not your own normalizer.** The
  round-trip test passed because it normalized both sides with the *project's*
  function; assert instead that `cognee._uri_to_key(fragment)` equals the key
  you intend — that would have flagged `3h`.
- **Simulate paid rebuilds offline first.** Reproducing the exact match
  algorithm over the current export gates cost and sets honest success bars.
- **Exact master hits bypass every fuzzy guard.** A dirty master name value
  (a company column carrying a bare region word) becomes a verified
  individual no guard can stop; the precision spot-check is the detector for
  this class, and master data quality is its bound.
- **Set success bars against the matchable population, not the raw entity
  count.** LLM extraction is nondeterministic (±500 entities across identical
  ingests) and most entities are unmatchable literals; bar to the ceiling the
  simulator reports, not to a round number.
- **Regenerating from a post-match export re-absorbs prior spellings** —
  cognee renames matched entity nodes to the individual's key, so exports show
  normalized keys as entity names. Expect the candidate pool to accumulate
  previous runs' keys and dedupe accordingly.

## Related Issues

- `docs/solutions/integration-issues/cognee-vercel-ai-gateway-integration.md`
  — the configuration-layer companion (gateway routing, caching, telemetry,
  Kuzu locking). Its pitfall 8 (fail-loud ontology-path guard) is the
  prerequisite to everything here: the file must load before matching
  semantics matter.
- Implementation: `agents/doc-intel/analysts/src/doc_intel_analysts/graph/individuals.py`
  (generator), `agents/doc-intel/analysts/tests/test_individuals.py` (guards),
  `references/ontology/welldrive.owl` (generated individuals block).
- Gate history: `benchmark/results/2026-07-06-ontology-individuals-gates.md`.
