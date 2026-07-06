# 2026-07-06 — doc-intel memory stage 1: both human gates PASSED

**R4 cost checkpoint (passed, Rob):** 20-doc stratified trial — 20/20 ok,
275,884 chars, cognify 67.2s, 723 nodes / 2,431 edges; trial cost well under
$1 (gateway dashboard); full-run estimate $5–15 accepted. Ledger:
`runs/doc-intel/graph/ledgers/2026-07-06-093831.csv`.

**Full ingest (after R4 go):** 311/311 parse-carrying documents (291 new +
20 trial), 30 no-parse-output rows classified, zero failures; 4.6M chars;
cognify 234.3s (sublinear). Ledger: `.../2026-07-06-095810.csv`. Graph:
6,943 nodes / 28,501 edges; nodes.csv + edges.csv exported.

**U7 entity-quality gate (passed, Rob):** spot-checks via the agent TUI,
including an off-list deep check on REVIVAL-STX-UNIT-A S732H whose answer
was verified exact against manifest ground truth (6/6 documents, correct
classes, path+page citations, honest sample-gap statement, and a flagged
vendor-template artifact instead of silent normalization). Evals:
graph-explore 4/4, delegation regression 4/4.

## Addendum — typed rebuild (post PR-6 review, Rob's option A)

PR-6 review caught that the original full ingest resolved the ontology path
one directory short; RDFLibOntologyResolver silently proceeded, so the gated
graph was built untyped. After the path fix (+ fail-loud guard), Rob chose a
clean rebuild: store wiped, 311/311 re-ingested (ledger
`.../2026-07-06-132037.csv`), cognify 248s, exports auto-refreshed (new
per-run export behavior). Rebuilt graph: 6,856 nodes / 28,595 edges, all
carrying ontology metadata; 12 nodes ontology_valid=true at the 80% fuzzy
cutoff — the class-only OWL matches few entity names, so enriching it with
individuals (operators, vendors, teams, counties) is the noted follow-up.
Both evals re-passed 4/4 against the rebuilt graph.
