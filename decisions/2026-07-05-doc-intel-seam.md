# 2026-07-05 — doc-intel: where eve ends and deepagents begins

## Decision

The TypeScript eve runtime owns the **session, the corpus, and the truth**;
the Python deepagents layer owns **specialist multi-document analysis**. They
meet at exactly one seam: an eve tool (`delegate_analysis`) that POSTs a
question plus resolved document references to a local/private deepagents HTTP
service, and gets back an answer with citations that eve **verifies against
its own corpus tools before presenting**.

```
user ⇄ eve (durable sessions, channels, approval, corpus tools, citations)
          │  delegate_analysis(question, document_refs[])   ← the seam
          ▼
      deepagents service (FastAPI, Python)
          ├─ orchestrator deep agent
          └─ per-document-class analyst SubAgents (programmatic configs)
                └─ read parsed content directly from the derived S3 bucket
```

## Division of labor

| Concern | Owner | Why |
| --- | --- | --- |
| Durable sessions, streaming, channels, HITL approval | eve | This is what eve *is*; deepagents has none of it |
| Corpus navigation + document reads (read-only, typed, page-cited) | eve tools | Filesystem-model fit; single enforcement point for read-only + citation discipline |
| Parse-on-demand + parse cache (derived bucket, open JSON) | eve tools | One writer to the cache; cost control in one place |
| Triage/routing knowledge | eve skills (Markdown) | Model-reasoned routing per house rule; no code classifiers |
| Multi-doc synthesis with specialist personas | deepagents SubAgents | Programmatic SubAgent configs are the house rule and LangChain's native strength; eve subagents would mean hand-maintaining N directories for what is one config table |
| Final answer + citation verification | eve | The agent that owns the user relationship never repeats an uncited claim |

## The seam contract

`POST /analyze` `{question, documents: [{key, entry_type, parsed_ref}]}` →
`{answer, citations: [{key, page}], analyst_notes}`. The deepagents service
reads parsed content itself (S3, same derived-bucket cache eve writes) so
document bodies never transit the seam; only references do. eve re-reads any
cited page it hasn't already seen before trusting a citation.

## Why not the alternatives

- **deepagents as orchestrator, eve as channel shim** — throws away eve's
  durability and filesystem-authored surface; fights both frameworks.
- **Everything in eve (TS subagents as analysts)** — violates the brief's
  requirement that analysts be programmatic deepagents SubAgents, and per-class
  analyst directories under `agent/subagents/` would be N hand-maintained
  copies of one pattern.
- **deepagents called in-process via a Python sidecar per request** — process
  spawn per call, no warm model clients, harder to deploy; HTTP keeps the
  layers independently deployable (Vercel runs Python via Fluid Compute).

## Consequences / trade-offs accepted

- Two runtimes to boot locally (eve dev + uvicorn); mitigated by a
  `docs`-documented two-command dev loop and a health-check tool response
  when the analyst service is down (eve degrades to single-doc answering).
- Citations can arrive wrong from the analyst layer; mitigated structurally —
  eve verifies before presenting (instructions.md requires it).
- The analyst service is stateless; long analyses re-read parsed content.
  Acceptable at 500-file sample scale.

## Also decided here

- `@aws-sdk/client-s3` added to doc-intel (runtime S3 access; shelling to the
  aws CLI would break on deploy). deepagents layer uses `boto3` equivalently.
- Analyst *classes* (which entry_types group under which analyst) live in an
  open JSON table in the repo knowledge layer, consumed programmatically by
  the Python service to generate SubAgent configs — one source of truth,
  portable off both runtimes.
