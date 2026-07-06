# WellDrive ontology

`welldrive.owl` (OWL, RDF/XML) steers Cognee's entity typing during cognify
(plan KTD5/U2). Open knowledge-layer artifact — review and edit freely; it is
regenerable from `references/analyst-classes.json` + core entity kinds, then
hand-shaped.

Shape: core classes (Well, Operator, ServiceVendor, Formation, County,
AssetTeam, Event, DocumentClass), a DocumentClass hierarchy — one group per
analyst class, one leaf per WellDrive entry_type (59, labels carry the exact
metadata string) — and object properties with domain/range (operatedBy,
servicedBy, locatedIn, penetrates, ownedBy, documentedBy, occurredOn,
performedBy, recordedIn).

Consumed by the ingest CLI via cognee's RDFLibOntologyResolver; contract
tests in `agents/doc-intel/analysts/tests/test_ontology.py`.
