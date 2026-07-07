# Concepts

Shared domain vocabulary for this project — entities, named processes, and status concepts with project-specific meaning. Seeded with core domain vocabulary, then accretes as ce-compound and ce-compound-refresh process learnings; direct edits are fine. Glossary only, not a spec or catch-all.

## Corpus

### Entry Type
The authoritative classification of a well-file document, stored as S3 object metadata on the source archive. All document routing and triage decisions key on entry type — never on filenames, which are vendor artifacts.

### Corpus Sample
The deterministic stratified subset of the full WellDrive archive that agents operate on, recorded in an open manifest with per-document parse status. Absence of a fact in the sample never implies absence in the full archive.

### Parse Tier
The cost/fidelity class assigned to a document's structured parsing. Tier A yields field extractions with per-field page citations; tiers B and C yield page-chunked Markdown; the lowest tier marks formats not worth parsing. A document with no usable parse output is "no-parse-output" — a classification, not a failure.

### Derived Bucket
The storage area holding everything computed *from* the corpus — parse outputs, ingest ledgers, graph exports — kept separate from the raw archive so derived data can be rebuilt or discarded without touching sources.

## Memory & Graph

### Knowledge Graph
doc-intel's entity-level memory over the corpus sample: wells, operators, vendors, formations, and events extracted from parsed documents and linked across them. A data product consumed through the agent and through open node/edge exports, deliberately portable off the engine that builds it.

### Provenance Tag
The document key carried into the graph with every ingested document, making each graph fact traceable to its source document. Provenance is two-tier: tags give the document; page-level attribution always comes from re-reading the parsed source before citation. A fact that cannot be pinned to a page is dropped, never cited with a guessed page.

### Ontology Validity
The per-entity flag marking that an extracted graph entity fuzzy-matched a named individual in the project ontology (80% similarity cutoff). Its meaning is only as strong as the individuals list: matched against corpus-derived names alone it signals consistency, not correctness — ground truth requires individuals verified against enterprise masters. Many entities (dates, depths, measurements) legitimately never validate.

A validated entity takes its matched individual's name in the graph and exports — matching rewrites identity, so downstream consumers join validated entities to the ontology by name.

### Named Individual
A concrete, verified instance of an ontology class — a specific well, operator, vendor, county, or asset team — as distinct from the class itself. Individuals are generated from corpus-seen spellings and verified against Snowflake masters, never hand-edited into the ontology file.

An individual's identifier doubles as its match key: the spelling of the identifier is the matching behavior, so identifiers are minted in the matcher's normalized form and must avoid characters the matcher treats as delimiters.

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
