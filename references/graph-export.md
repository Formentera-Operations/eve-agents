# Knowledge-graph export (nodes/edges CSV)

The doc-intel knowledge graph exports after each ingest run to:

```
s3://formentera-welldrive-derived/runs/doc-intel/graph/nodes.csv
s3://formentera-welldrive-derived/runs/doc-intel/graph/edges.csv
```

Open tabular interchange (plan R8/R9): any consumer — dbt/Snowflake,
a notebook, a dashboard — reads these without touching Cognee.

## Schema

**nodes.csv** — `id` (graph node id, stable within an export), `type`
(node kind: Entity, EntityType, TextDocument, DocumentChunk, TextSummary,
NodeSet), `name` (display name, ≤500 chars), `properties` (JSON object of
remaining attributes; includes `s3key:`-prefixed node_set tags on document
nodes).

Ontology typing on Entity nodes: `properties.ontology_valid = true` marks an
entity that matched a named individual in `references/ontology/welldrive.owl`
(cognee renames the entity to the individual's key on match, so `name` joins
directly to the OWL individual and its class — Well, Operator, ServiceVendor,
County, AssetTeam). Extractor-assigned types travel as `is_a` edges from
Entity nodes to EntityType nodes, not in the `type` column.

**edges.csv** — `source`, `target` (node ids), `label` (relationship, e.g.
operatedBy / servicedBy / occurredOn / is_part_of), `properties` (JSON).

## Worked example: wells → vendors in SQL

Load both files (Snowflake `COPY INTO`, or `read_csv` in dbt-duckdb), then:

```sql
select w.name as well, v.name as vendor
from edges e
join nodes w on w.id = e.source and w.type = 'Well'
join nodes v on v.id = e.target and v.type = 'ServiceVendor'
where e.label = 'servicedBy';
```

Provenance: document nodes carry their corpus S3 key in `properties`
(`s3key:<key>`); join through document edges to trace any fact to its
source file in `s3://formentera-welldrive`.

Refreshed by `uv run python -m doc_intel_analysts.graph.export` (run from
`agents/doc-intel/analysts/`, service stopped). Ingest run ledgers live
under `runs/doc-intel/graph/ledgers/`.
