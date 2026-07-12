# Agent Runs trace retention — allow everything, with two riders

**Status:** ACCEPTED (Rob, 2026-07-11). Gates the production deploy milestone;
supersedes the open "governance call on trace retention" flagged 2026-07-05
in the post-Phase-B follow-ups.

**Decision:** When doc-intel deploys to Vercel and Agent Runs begin
collecting, traces retain **full-fidelity content — tool inputs and outputs
included** (i.e., corpus page text appears in traces). No redaction shim, no
truncation of tool I/O. Two binding riders:

1. **Access-scoping invariant:** Vercel dashboard / MCP principals with
   Agent Runs visibility on the doc-intel project must remain a subset of
   the people who already hold read access to the raw WellDrive archive
   (S3). Traces add ~zero marginal exposure only while this invariant
   holds; enforce it whenever project membership changes.
2. **Class-contingent revisit trigger:** this posture is decided against
   today's indexed corpus (overwhelmingly drilling/completions paper). It
   MUST be revisited at the moment land/legal entry types ingest — title
   opinions, JOA confidential exhibits, division orders — which is also
   when the sensitivity-classes work (channel authorization) is due. JOA
   confidentiality is contractual; that revisit deserves a counsel-grade
   read, not an engineering default.

**Context:** Agent Runs (Vercel changelog 2026-07: MCP tools
`list_agent_runs` / `get_agent_run_trace`, CLI `vercel agent-runs … --json`)
automatically capture turns, reasoning, tool calls, token usage, and tool
I/O for deployed eve agents. For doc-intel, tool output *is* corpus content
(`read_evidence` returns page text). The 2026-07-11 dueling-wizards session
(DUELING_WIZARDS_REPORT.md) surfaced the collision between trace retention
and document-level authorization, making the retention call the first
domino in front of the deploy milestone.

**Reasoning:**
- **No new egress boundary.** Page text already transits Vercel (AI
  Gateway) into model-provider context windows on every call. Traces add
  retention + queryability to an existing path, not a new crossing.
- **Redaction destroys the improvement loop asymmetrically.** Failure
  forensics, the correction-to-regression workflow, trace-graded behavioral
  benchmarks, and the answer-ledger derivation all consume raw tool I/O.
- **Redaction blinds the security agenda where it matters most:** detecting
  corpus-borne prompt injection means seeing the hostile document text that
  steered a tool-call sequence. A redacted trace is a useless audit log for
  exactly that threat.
- Full-fidelity traces are the compounding tuning asset (qualitative +
  quantitative), chosen at the moment it is cheapest.

**Alternatives considered:**
- *Redact/truncate sensitive-class tool I/O in traces:* rejected for now —
  requires sensitivity classes that don't exist yet, cripples debugging,
  and protects against exposure the access-scoping rider already prevents.
  Becomes live again at the land/legal revisit.
- *Defer deploy until sensitivity classes exist:* rejected — blocks the
  entire Evidence Desk / observability / distribution chain to protect
  document classes that are mostly not yet indexed.

**Open item carried:** confirm Vercel's actual retention window and
deletion path for Agent Runs data on the team plan (changelog is silent).
If retention is indefinite with no deletion path, the revisit trigger
gains teeth.

**Owner:** Rob.
