# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A pnpm workspace for building and shipping multiple [Vercel eve](https://eve.dev)
agents. Each agent under `agents/<name>/` is an independent eve app (own
`package.json`, own deploy). Durable knowledge is shared at the repo root.
`agents/starter/` is the convention exemplar — when adding anything to any
agent, match its patterns.

```
agents/<name>/       # one eve app per directory
  agent/             # the authored agent surface (eve walks this)
    agent.ts         #   runtime config (model via AI Gateway id string)
    instructions.md  #   always-on system prompt
    tools/           #   one tool per file — filename IS the tool name
    skills/          #   runtime skills the DEPLOYED AGENT's model loads
    channels/        #   HTTP/messaging entrypoints + auth
  evals/             # agent-behavior tests (eve eval; needs gateway creds)
  tests/             # unit tests (node:test; no network, no creds)
skills/              # procedures for SESSIONS working on this repo — start here
references/          # distilled framework knowledge (eve-conventions.md)
decisions/           # decision records, YYYY-MM-DD-topic.md
```

Two different "skills" concepts exist — never mix them: root `skills/` teach
*you* how to work here; `agents/*/agent/skills/` are loaded by the deployed
agent's model at runtime.

## House rules (never cross these)

1. **eve conventions are law.** `agent/` directory layout, tools as files,
   skills as Markdown, snake_case tool names, ESM/NodeNext. Before writing
   eve code, read `references/eve-conventions.md`; when in doubt, the
   framework's bundled docs at `agents/<name>/node_modules/eve/docs/` are the
   source of truth (start with `reference/project-layout.md` and
   `tools/overview.mdx`).
2. **Durable knowledge lives at the repo root** (`skills/`, `references/`,
   `decisions/`) in open Markdown, shared across agents — never buried inside
   an agent directory. Agent harnesses are disposable; this layer is not.
   Record structural decisions in `decisions/YYYY-MM-DD-topic.md`.
3. **No secrets in the repo, ever.** `.env*` is gitignored; credentials flow
   through Vercel Connect / AI Gateway env only (`npx eve link` pulls gateway
   credentials into the agent's `.env.local`). Never return secrets from a
   tool.
4. **Clean conventional commits** (`feat:`, `fix:`, `chore:`, `docs:`, with
   `feat(starter):`-style scopes). One logical change per commit; work lands
   as reviewable history, not one blob.

## Commands

Run eve CLI commands **from inside the agent directory** (eve resolves its app
root and `.env`/`.env.local` from cwd). Workspace-wide scripts run from the root.

```bash
pnpm install                 # root: install everything
pnpm typecheck && pnpm test  # root: verify all agents (do this before declaring done)

cd agents/starter
npx eve info                 # discovered surface + diagnostics — first stop when anything misbehaves
npx eve dev                  # dev server + interactive terminal REPL (the dev TUI)
npx eve dev --no-ui          # headless server for scripted verification (see below)
pnpm test                    # unit tests for this agent only
node --test tests/get_weather.test.ts   # a single test file
npx eve eval                 # behavior evals (boots a real server; needs AI Gateway creds)
npx eve link                 # link Vercel project, pull AI Gateway creds (interactive)
npx eve deploy               # deploy to Vercel production
```

**Never run bare `npx eve dev` as a background process** — it opens a TUI that
swallows the process. For hands-off verification: `npx eve dev --no-ui`, wait
for the printed URL, then exercise `POST /eve/v1/session` and
`GET /eve/v1/session/:id/stream`; kill the server when done.

## Adding a tool

Follow `skills/adding-a-tool.md` exactly. The short version: create
`agents/<name>/agent/tools/<tool_name>.ts` (snake_case filename — it IS the
model-facing tool name; there is no `name` field anywhere in eve),
default-export `defineTool` from `eve/tools` with a Zod `inputSchema`, keep
pure logic in a named export, and add `tests/<tool_name>.test.ts` using
`node:test` with `fetch` stubbed. `agents/starter/agent/tools/get_weather.ts`
and its test are the template — copy their shape.

Verification order after any agent change:
`npx eve info` (0 diagnostics, file discovered) → `pnpm typecheck` →
`pnpm test` → exercise it in the dev TUI or via `--no-ui` + HTTP.

## Testing model

- **Unit tests** (`tests/*.test.ts`, `node:test`): every tool's logic. No
  network, no credentials — stub `globalThis.fetch`. `defineTool` returns the
  plain definition object, so tests import the default export and call
  `.execute(input, {} as never)` directly. Import tool files **with the `.ts`
  extension** (Node strips types natively; `allowImportingTsExtensions` is on).
- **Evals** (`evals/*.eval.ts`, `defineEval` from `eve/evals`): agent
  behavior — did the model call the right tool, say the right thing. They need
  AI Gateway credentials, so they are not part of the default `pnpm test` bar.
  An `evals/` directory requires exactly one `evals.config.ts`.

## Adding a new agent

```bash
cd agents && npx -y eve@latest init <kebab-name>
```

Then: delete its `package-lock.json` (`trash`, not `rm -rf` — a hook blocks
it), run `pnpm install` from the root (the workspace glob `agents/*` picks it
up), set `engines.node` to `>=24`, replace the placeholder
`agent/instructions.md`, and commit the pristine scaffold separately from your
changes. Non-Node agents (e.g. a Python deepagents layer) also live under
`agents/` — pnpm ignores directories without a `package.json`.

## Gotchas that will otherwise cost you time

- `eve info`'s human output does not render a Tools section in eve 0.19 — to
  confirm discovery, check `Diagnostics: 0 errors` and read
  `.eve/discovery/agent-discovery-manifest.json`.
- The stack is ESM/NodeNext throughout: `"type": "module"`, TS
  `module: NodeNext`, Node ≥ 24. The `#*` import alias maps to `./agent/*`.
- Model ids in `agent.ts` are AI Gateway strings (`"anthropic/claude-sonnet-5"`)
  — do not install per-provider SDK packages or add any dependency without
  explicit approval.
- Tool `execute` runs in the app runtime (full `process.env`), outputs must be
  JSON-serializable, and interrupted steps re-run — keep side effects
  idempotent or gate them with `approval: always()` from `eve/tools/approval`.
- Git hooks here block `rm -rf` (use `trash`) and block any command string
  mentioning secret-file patterns — phrase commit messages accordingly.
