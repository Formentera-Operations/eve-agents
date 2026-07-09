# WellDrive ontology

`welldrive.owl` (OWL, RDF/XML) steers Cognee's entity typing during cognify
(plan KTD5/U2). Open knowledge-layer artifact in two layers:

**Class layer** (hand-shaped): core classes (Well, Operator, ServiceVendor,
Formation, County, AssetTeam, Event, DocumentClass), a DocumentClass
hierarchy — one group per analyst class, one leaf per WellDrive entry_type
(59, labels carry the exact metadata string) — and object properties with
domain/range (operatedBy, servicedBy, locatedIn, penetrates, ownedBy,
documentedBy, occurredOn, performedBy, recordedIn). Edit freely.

**Named individuals** (generated — never hand-edit): everything between the
`BEGIN/END GENERATED INDIVIDUALS` markers. Corpus-seen spellings of wells,
operators, vendors, counties, and asset teams, verified against Snowflake
masters. Each individual's URI fragment IS cognee's fuzzy-match key
(lowercase, spaces→underscores — `RDFLibOntologyResolver._uri_to_key` form);
`rdfs:label` keeps the document spelling for humans; `rdfs:comment` names the
verifying master table only (raw master keys stay in the gitignored report).

## Regenerating the individuals

From the repo root, with graph exports current (ingest auto-exports):

```bash
# 1. Export master name lists (read-only; schema follows your dbt build)
snow sql -f references/ontology/masters/gold_dim_well.sql \
  -D "masters_schema=FO_RAW_DB.dev_dbt_rob_stover" --format csv \
  > agents/doc-intel/analysts/.masters/gold_dim_well.csv
snow sql -f references/ontology/masters/gold_dim_vendor.sql \
  -D "masters_schema=FO_RAW_DB.dev_dbt_rob_stover" --format csv \
  > agents/doc-intel/analysts/.masters/gold_dim_vendor.csv

# 2. Regenerate (pulls nodes/edges CSVs from the derived bucket if absent)
cd agents/doc-intel/analysts
uv run python -m doc_intel_analysts.graph.individuals

# 3. Rebuild the graph on the enriched ontology (service stopped)
trash .cognee && uv run python -m doc_intel_analysts.graph.ingest
```

Unverified candidates land in `.masters/unverified-report.csv` (gitignored)
with their nearest master and score — misses are visible, never silent.

`aliases.csv` (hand-curated, committed) carries the exceptions no string
metric can bridge — corporate renames ("Liberty Oilfield Services" →
LIBERTY ENERGY SERVICES LLC) and brands that bill through a parent (Baroid
is a Halliburton product service line, Rob 2026-07-09). Aliases resolve
exactly, apply even to untyped sweep candidates, and fail loud when the
named master is missing from the export.

Consumed by the ingest CLI via cognee's RDFLibOntologyResolver; contract
tests in `agents/doc-intel/analysts/tests/test_ontology.py` and
`tests/test_individuals.py`.
