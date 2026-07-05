# 2026-07-05 — Repo topology: pnpm workspace, knowledge at root

## Decision

`eve-agents` is a pnpm workspace monorepo. Each agent is an independent
package under `agents/<name>/`. Durable knowledge (skills, references,
decisions) lives at the repo root in open Markdown, shared across agents.

```
eve-agents/
├── agents/<name>/     # one eve app per directory (own package.json, own deploy)
├── skills/            # repo skills: procedures for working in this repo
├── references/        # distilled framework/domain knowledge
├── decisions/         # this directory — one file per decision
└── CLAUDE.md          # how work happens here (the contract for agent sessions)
```

## Context

We will ship multiple Vercel eve agents over time from this repo. The first
scaffold (`agents/starter`) is the convention exemplar. A document-intelligence
agent (with a Python deepagents layer) lands next.

## Reasoning

- **One repo, many agents**: eve derives the agent name from its
  `package.json` name, and each agent dir is a self-contained eve app root
  (`eve dev`, `eve deploy` run from inside it). A workspace keeps installs
  fast and dependencies aligned without coupling the agents.
- **Knowledge at root, not inside agents**: an agent directory is a
  disposable harness — it can be rewritten, replaced, or deleted. Skills,
  references, and decisions must survive that, so they live at the root.
  Note the distinction: root `skills/` are procedures for *sessions working
  on this repo*; `agents/<name>/agent/skills/` are runtime skills the
  *deployed agent's model* loads. They never mix.
- **Non-Node agents fit**: pnpm only treats directories with a
  `package.json` as workspace packages, so a Python agent (e.g. a deepagents
  layer beside or inside an agent dir) slots under `agents/` with zero
  workspace config changes.

## Alternatives considered

- **One repo per agent** — rejected: knowledge and conventions would fork
  per repo; the shared layer is the point.
- **Shared TypeScript packages (`packages/`)** — deferred: no shared code
  exists yet. Add `packages/*` to `pnpm-workspace.yaml` when the second
  agent actually needs shared code, not before.
- **npm workspaces** — rejected: pnpm is the house standard; stricter
  hoisting catches phantom dependencies.

## Trade-offs accepted

- `eve` versions can drift between agents; acceptable, each agent deploys
  independently. Align them opportunistically.
- Commands must run from the agent directory (eve resolves its app root from
  cwd); mitigated with `pnpm --filter <name>` from the root.
