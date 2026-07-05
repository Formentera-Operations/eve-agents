# eve-agents

Workspace for building and shipping [Vercel eve](https://eve.dev) agents.
Multiple agents live here over time; conventions and knowledge are shared at
the root, agents are independent deployables under `agents/`.

**Working in this repo with an AI session? `CLAUDE.md` is the contract — read
it first.**

## Layout

```
agents/           # one eve app per directory — own package.json, own deploy
  starter/        # convention exemplar: copy its patterns for new agents
skills/           # procedures for working in this repo (humans + AI sessions)
references/       # distilled framework and domain knowledge
decisions/        # decision records (YYYY-MM-DD-topic.md)
```

## Quickstart

```bash
pnpm install
cd agents/starter
npx eve info      # discovered surface + diagnostics
npx eve dev       # dev server + terminal REPL
```

Model auth: `npx eve link` (from the agent directory) links a Vercel project
and pulls AI Gateway credentials into `.env.local`. No secrets are ever
committed.

## Verify

```bash
pnpm typecheck && pnpm test    # from the root, covers all agents
```
