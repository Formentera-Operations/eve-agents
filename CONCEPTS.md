# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## Corpus

### Entry Type
The authoritative classification of a well-file document, stored as S3 object metadata on the source archive. All document routing and triage decisions key on entry type — never on filenames, which are vendor artifacts.

### Corpus Sample
The deterministic stratified subset of the full WellDrive archive that agents operate on, recorded in an open manifest with per-document parse status. Absence of a fact in the sample never implies absence in the full archive.

### Parse Tier
The cost/fidelity class assigned to a document's structured parsing. Tier A yields field extractions with per-field page citations; tiers B and C yield page-chunked Markdown; the lowest tier marks formats not worth parsing. A document with no usable parse output is "no-parse-output" — a classification, not a failure.

### Format Gate
The verdict, taken from a document's key alone before any bytes are fetched, that routes it into parsing or deliberately declines it as out of scope. A gate verdict is a property of the document, not of an attempt to process it, so unchanged bytes can never change the outcome — gate skips are terminal by design.

### Ingest Ledger
The per-document state record of an evidence-store ingest pass: every document ends a pass as complete, deliberately skipped, or failed, together with the content fingerprint that verdict applies to. The ledger is what makes multi-day ingests resumable — a new pass fast-forwards past settled documents and reprocesses only the new, changed, and failed.

The ledger row is written last for each document, so an interrupted document has no settled row and simply redoes. Terminality is explicit: skips are terminal for the exact bytes they judged, while failures — fetch or parse errors — are always visible in failure counts and retried on later passes, never absorbed into skip counts. Two deterministic image verdicts are the exception: an image whose header declares more pixels than the project ceiling, or bytes the image library cannot identify, skips terminally for the judged checksum — retrying unchanged bytes can never change either outcome, and a changed file still reopens automatically. Content rows for a document that never reached the ledger are swept at the start of the next pass.

### Derived Bucket
The storage area holding everything computed *from* the corpus — parse outputs, ingest ledgers, graph exports — kept separate from the raw archive so derived data can be rebuilt or discarded without touching sources.

## Memory & Graph

### Knowledge Graph
doc-intel's entity-level memory over the interpreted slice of the corpus: wells, operators, vendors, formations, and events extracted from parsed documents and linked across them. A data product consumed through the agent and through open node/edge exports, deliberately portable off the engine that builds it.

### Selective Enrichment
The pattern by which the knowledge graph grows: the evidence store nominates entity-dense documents worth interpreting, and the graph ingests only those — never the whole corpus. Interpretation cost concentrates where questions actually land, while the evidence store answers verbatim for everything else.

Ontology changes are batched ahead of rebuilds rather than triggering them, because a full re-interpretation is the expensive unit of work; validation counts therefore lag ontology changes until the next batched rebuild.

### Provenance Tag
The document key carried into the graph with every ingested document, making each graph fact traceable to its source document. Provenance is two-tier: tags give the document; page-level attribution always comes from re-reading the parsed source before citation. A fact that cannot be pinned to a page is dropped, never cited with a guessed page.

### Ontology Validity
The per-entity flag marking that an extracted graph entity fuzzy-matched a named individual in the project ontology above a similarity cutoff. Its meaning is only as strong as the individuals list: matched against corpus-derived names alone it signals consistency, not correctness — ground truth requires individuals verified against enterprise masters. Many entities (dates, depths, measurements) legitimately never validate.

A validated entity takes its matched individual's name in the graph and exports — matching rewrites identity, so downstream consumers join validated entities to the ontology by name.

### Named Individual
A concrete, verified instance of an ontology class — a specific well, operator, vendor, county, or asset team — as distinct from the class itself. Individuals are generated from corpus-seen spellings and verified against Snowflake masters, never hand-edited into the ontology file.

An individual's identifier doubles as its match key: the spelling of the identifier is the matching behavior, so identifiers are minted in the matcher's normalized form and must avoid characters the matcher treats as delimiters.

### Ontology Alias
A hand-curated equivalence from a corpus spelling to a master-verified identity, reserved for names no string similarity can bridge — corporate renames, former trade names, and brands that bill through a parent company. Facility and location mentions of a firm are never aliased to it; an office is not the company.

Aliases are exact-match and take precedence over all fuzzy verification, and they fail loudly when the master identity they name is absent — a typo breaks regeneration rather than minting a false individual.

### Matchable Ceiling
The measurable upper bound on how many extracted entities can ever achieve ontology validity in a given corpus — the population of genuine well/organization/place/team mentions, excluding the majority of entities (dates, depths, measurements) that no named individual can represent. Success bars for enrichment are set against this ceiling, measured by offline simulation, not against the raw entity count.

### Evidence Store
The corpus's indexed-retrieval leg: documents parsed into page-keyed layers (page text, page screenshots, extracted figures) and searched mechanically at query time — semantic, keyword, and visual. Interpretation happens at read time in the agent loop, unlike the Knowledge Graph, whose interpretation happens once at ingest. The two compose: the graph recalls what the corpus means; the evidence store retrieves what the corpus says, page-cited.

### Egress Guard
The named fail-loud check that refuses to initialize any model-calling component unless every outbound path — LLM, embeddings, telemetry — points at the approved gateway. Exists because vendored AI libraries default unset paths to their own providers silently.

## Agents

### Analyst Class
A grouping of entry types under one specialist analyst persona, defined in an open table from which analyst configurations are generated programmatically. Routing and per-class model choice are data, never code branches.

### Human Gate
A named checkpoint inside an autonomous run that only the product owner can pass — a cost checkpoint before spend scales, a quality verdict before results are trusted. Runs stop and surface at gates rather than proceeding on ambiguity.
