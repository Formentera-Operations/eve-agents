# Context layer / answer ledger — direction noted, build deferred

**Status:** PROPOSED — deliberately deferred until evidence-store Phase B and
the production deploy land. Revisit when Vercel Agent Runs traces exist.

**Decision recorded:** doc-intel's fourth layer, when built, is an **answer
ledger** — persisting each verified agent answer as first-class, queryable
data (question, answer text, cited pages, ontology-resolved entities,
timestamp, session) — NOT an adoption of a graph vendor or a re-architecture.

**Context:** Prompted by Neo4j's graph / knowledge graph / context graph
series (2026-07, marketing-oriented but taxonomically useful). Their tiers:
a graph answers *what is connected*, a knowledge graph *what connections
mean*, a context graph *what matters right now* — task, history, agent
decisions, and state, linked to evidence.

Mapping to doc-intel: tier 2 is already strong (OWL ontology +
master-verified individuals = the "unified business meaning" layer). Tier 3
is absent as a persistent layer, but the architecture already produces its
raw material on every run and discards it:

- every answer carries (s3key, page) citations — claim→evidence edges
- cited entities carry ontology-valid names — free joins into the graph
- the evidence ledger tracks per-document state; the manifest tracks routing
- post-deploy, Agent Runs traces capture the full decision path

The provenance discipline (citations verified before presentation, facts
without pages dropped) is the hard part of a context graph, and it is done.
The missing piece is only persistence.

**What it buys:** compounding institutional memory ("what have we already
established about well X, from which pages"), an audit trail for every claim
the agent has made, and — strongest fit — the land & title domain, where a
title runsheet literally *is* a context graph (instruments over tracts over
time with per-tract current state).

**Alternatives considered:**
- *Adopt Neo4j / a dedicated context-graph product:* rejected — no new
  vendor needed; one Lance table or a cognee node-set suffices, and the
  existing legs already made the right structural split (graph interprets at
  ingest, evidence store at read time).
- *Build now:* rejected — Agent Runs traces (post-deploy) are the natural
  feed, and memory stage 2 (deepagents Store) overlaps; building before
  those exist means building it twice.

**Unifies two parked roadmap items:** memory stage 2 and Agent Runs
adoption are both partial versions of this layer; design them together.

**Supersedes:** nothing. **Owner of the go decision:** Rob.
