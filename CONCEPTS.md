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

### Egress Guard
The named fail-loud check that refuses to initialize any model-calling component unless every outbound path — LLM, embeddings, telemetry — points at the approved gateway. Exists because vendored AI libraries default unset paths to their own providers silently.

## Agents

### Analyst Class
A grouping of entry types under one specialist analyst persona, defined in an open table from which analyst configurations are generated programmatically. Routing and per-class model choice are data, never code branches.

### Human Gate
A named checkpoint inside an autonomous run that only the product owner can pass — a cost checkpoint before spend scales, a quality verdict before results are trusted. Runs stop and surface at gates rather than proceeding on ambiguity.
