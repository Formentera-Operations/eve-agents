# Company brain as shared recall infrastructure — agents consume via connections

**Status:** ACCEPTED (Rob, 2026-07-12) as architectural direction. The
doc-intel graph-leg migration it implies is **gated on the provenance
precondition below** — direction now, retirement later.

**Decision recorded:** the company brain — the hosted cognee MCP service
(Azure Container Apps, bearer auth, `recall` tool; built and deployed from
the separate `company-brain` repo) — is the **long-term shared recall layer
for all eve agents in this workspace**. Agents integrate as thin consumers
through the `agent/connections/` slot (hosted MCP, allow-listed tools),
never by embedding their own graph stacks. Memory is infrastructure;
agents are clients.

**Context:** PR #32 shipped the first such connection (`brain.ts`: recall
over Bull Mountain 31-18 + Wildcat Hollow well files and land documents,
with three E2E evals including a fail-closed out-of-coverage gate); PR #33
rehomed it from the starter template to doc-intel, whose corpus is the
brain's exact scope. Meanwhile doc-intel still embeds its own cognee/Kuzu
graph leg inside the analysts service — two recall surfaces now coexist on
one agent. The brain deployment also proves the ACA-hosted-cognee pattern
that this repo's Phase 4 was still treating as future work.

**Implications:**

1. **The analysts sidecar slims toward evidence-store-only.** Its durable
   identity is the LanceDB + LiteParse leg (page-cited retrieval, the
   ingest ledger, vision reads). Graph interpretation trends out of the
   sidecar and into the brain service as the brain matures.
2. **Phase 4's Kuzu persistence question dissolves rather than resolves**
   once migration completes — the `company-brain` repo owns the graph
   store's lifecycle, hosting, and durability. Until migration, Phase 4
   carries the interim note: the embedded `.cognee` store is not
   rebuildable from S3 exports (loss = a ~$95 cognify rebuild) and needs
   either a persistent volume or an S3 sync habit, plus an
   embedded-DB-on-NFS locking check.
3. **Provenance precondition (the gate):** doc-intel's embedded graph leg
   is retirable only when brain recall carries document-level provenance
   of the grade `query_knowledge_graph` returns today — `evidence_doc_ids`
   that route into `read_evidence` for page-level verification before
   presentation. The brain's recall currently disclaims page-precise
   lookups by design; the verified-citation chain is doc-intel's identity
   and MUST survive the migration. Provenance work lands in the
   `company-brain` repo; this repo's gate is an eval proving the
   brain-sourced answer path verifies citations end-to-end.
4. **Interim routing doctrine (near-term follow-up):** while both surfaces
   coexist, doc-intel's instructions need one deliberate bullet — brain
   recall for cross-document narrative synthesis; the graph leg for
   anything that must end in a page citation. Two overlapping recall
   surfaces without doctrine means the model arbitrates silently.
5. **The answer ledger's natural home is the brain.** The deferred fourth
   layer (`2026-07-07-context-layer-answer-ledger.md`) — verified answers
   persisted as queryable data — is, in this architecture, brain memory
   fed from the verified-answer path. Design them together.
6. **Governance escalates with sharing.** One token-bearing service
   fronting multiple corpora for multiple agents makes document-level
   authorization (the 2026-07-11 ideation session's blind spot #2) and
   per-agent/per-corpus scoping prerequisites before non-well-file
   corpora join the brain.

**Alternatives considered:**
- *Per-agent embedded graph stacks:* rejected — N cognee installations, N
  persistence stories, N ontology copies, and no cross-agent memory;
  doc-intel's four documented cognee integration scars would be re-earned
  per agent.
- *Sharing via eve subagents or a common library:* rejected — doesn't
  cross the TS/Python seam, doesn't serve non-eve consumers (Claude
  estate, future surfaces), and couples agents to a dependency pin the
  brain repo already manages once.
- *Permanent coexistence without doctrine:* rejected — overlapping recall
  surfaces with silent model arbitration is the failure mode; coexistence
  is a gated transition state, not the end state.

**Trade-offs accepted:** a network hop and per-agent token management
replace in-process calls; the brain becomes critical shared infrastructure
(its availability is every consumer's memory availability); the
provenance gate depends on work in a repo outside this one.

**Supersedes:** nothing. Extends `2026-07-05-doc-intel-seam.md` with a
second sanctioned cross-service seam (`connections/` for shared services,
alongside `delegate_analysis` for owned analysis); reshapes what
`2026-07-09-evidence-store-migration.md` Phase 4 ultimately hosts; gives
`2026-07-07-context-layer-answer-ledger.md` its candidate home.
**Owner:** Rob (migration timing; provenance gate lands in `company-brain`).
