# eve framework conventions (distilled from eve@0.19 bundled docs)

Source of truth: `agents/<name>/node_modules/eve/docs/` (bundled with the
package — read those, not memory, when behavior is in doubt). Fallback:
https://eve.dev/docs. This file is the distilled working set.

## Identity comes from the path

You never write a `name` or `id` on a `define*` call. The file path is the
identity, and filenames are **snake_case** because the model sees them:

| Path | Becomes |
| --- | --- |
| `agent/tools/get_weather.ts` | tool `get_weather` |
| `agent/skills/summarize.md` | skill `summarize` |
| `agent/connections/linear.ts` | connection `linear` |
| `agent/subagents/researcher/agent.ts` | subagent `researcher` |
| `evals/weather/forecast.eval.ts` | eval `weather/forecast` |

The root agent is named by its `package.json` `name`.

## Authored slots under `agent/`

- `agent.ts` — runtime config via `defineAgent` (from `eve`). `model` takes a
  gateway id string like `"anthropic/claude-sonnet-5"` (routes through Vercel
  AI Gateway). Optional: `reasoning`, `compaction`, `limits`, `outputSchema`.
- `instructions.md` — the always-on system prompt. Required on the root agent.
- `tools/` — one tool per file, default-export `defineTool` (from `eve/tools`):
  `description` (written for the model), `inputSchema` (Zod; required — use
  `z.object({})` for no input), `execute(input, ctx)` (sync or async), optional
  `outputSchema`, optional `approval` (from `eve/tools/approval`: `always()`,
  `once()`, `never()`), optional `toModelOutput` to shrink what the model sees.
- `skills/` — runtime procedures the deployed agent's model loads on demand.
  Flat `.md` file, or packaged dir with `SKILL.md` (needs `description`
  frontmatter), or `defineSkill` (from `eve/skills`) when you need typed values.
- `channels/` — HTTP/messaging entrypoints (root only). The scaffolded
  `channels/eve.ts` wires auth: `vercelOidc()` + `localDev()` + placeholder.
- `connections/` — external MCP/OpenAPI servers, one per file.
- `lib/` — shared authored helper code, import-only.
- `subagents/<id>/` — child agents; `agent.ts` requires a `description`.
- `schedules/`, `hooks/`, `sandbox/`, `instrumentation.ts` — see bundled docs.

Tools run in the app runtime with `process.env` access — not in the sandbox.
Tool outputs must be JSON-serializable; never return secrets from a tool.
Interrupted steps re-run, so make side effects idempotent or gate on approval.

## Module system

ESM only, `"type": "module"`, TypeScript `module`/`moduleResolution` =
`NodeNext`, strict. Package imports alias `#*` → `./agent/*`. Node ≥ 24.

## Evals are the test surface

Evals live in `evals/*.eval.ts` at the app root (sibling of `agent/`, never
inside it). Each file default-exports `defineEval` (from `eve/evals`) with an
`async test(t)`: drive with `t.send(...)`, assert with `t.succeeded()`,
`t.calledTool("name")`, `t.check(t.reply, includes("..."))`. `evals/` requires
exactly one `evals.config.ts` (default-export `defineEvalConfig`). Run with
`eve eval` (boots a real local server; needs AI Gateway credentials unless the
agent's model is `mockModel`). Deterministic tool logic can additionally be
unit-tested by importing the tool module and calling `.execute()` directly —
`defineTool` returns the plain definition object.

## CLI working set

Run from the agent directory (eve resolves its app root from cwd; it loads
`.env`/`.env.local` from there):

| Command | Use |
| --- | --- |
| `npx eve info` | First stop when anything misbehaves: prints discovered surface + diagnostics |
| `npx eve dev` | HMR dev server + interactive terminal REPL (the "dev TUI") |
| `npx eve dev --no-ui` | Headless dev server for scripted/agent verification |
| `npx eve eval` | Run evals against a local server (or `--url` for remote) |
| `npx eve build` / `start` | Production build / serve built output |
| `npx eve link` | Link to a Vercel project; pulls AI Gateway credentials into `.env.local` |
| `npx eve deploy` | Deploy to Vercel production |

Headless verification pattern: `npx eve dev --no-ui`, wait for the URL, then
`POST /eve/v1/session` / `GET /eve/v1/session/:id/stream`. Never run bare
`npx eve dev` as a background process from a coding agent — it opens a TUI.

Debug artifacts land under `.eve/` (`discovery/diagnostics.json`,
`compile/compiled-agent-manifest.json`); gitignored.

## Auth and credentials

Model auth flows through the Vercel AI Gateway: `eve link` drops
`VERCEL_OIDC_TOKEN` / `AI_GATEWAY_API_KEY` into the agent's `.env.local`
(gitignored). No provider API keys in code or in the repo, ever.
