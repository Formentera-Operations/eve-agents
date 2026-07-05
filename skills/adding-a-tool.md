# Skill: add a tool to an agent

Procedure for adding a typed tool to any agent in this repo. Follow it exactly;
every step is load-bearing.

1. **Name the file, not the tool.** Create
   `agents/<name>/agent/tools/<tool_name>.ts` with a snake_case filename —
   the filename is the model-facing tool name. No `name` field exists.

2. **Shape.** Default-export `defineTool` from `eve/tools` with a Zod
   `inputSchema` and a `description` written for the model:

   ```ts
   import { defineTool } from "eve/tools";
   import { z } from "zod";

   export default defineTool({
     description: "One sentence: what it does and when the model should call it.",
     inputSchema: z.object({ city: z.string().min(1) }),
     async execute({ city }) {
       return { city, condition: "Sunny" }; // JSON-serializable only
     },
   });
   ```

   Keep pure logic in a named export (or in `agent/lib/`) so it can be
   unit-tested without the eve runtime. Recoverable failures (bad upstream
   status, unparseable payload, nothing found) return an
   `{ error: "why" }` object rather than throwing — the model reads it and
   recovers. Side-effecting or irreversible tools get `approval: always()`
   from `eve/tools/approval`.

3. **Test it.** Two layers, pick per what the tool does:
   - **Unit test (always)**: `agents/<name>/tests/<tool_name>.test.ts` using
     `node:test`. Import the tool's default export and call
     `await tool.execute(input, {} as never)` — `defineTool` returns the plain
     definition object. Stub network calls; don't hit the real network in tests.
   - **Eval (when agent behavior matters)**: `agents/<name>/evals/<case>.eval.ts`
     with `defineEval`; assert `t.calledTool("<tool_name>")`. Evals boot a real
     server and need AI Gateway credentials, so they don't run in plain CI.

4. **Verify, in order** (from `agents/<name>/`). All four steps are required;
   the first three plus the boot check need no credentials:
   ```bash
   npx eve info                # 0 diagnostics; discovery manifest lists the tool
   pnpm typecheck              # green
   pnpm test                   # unit tests green
   npx eve dev --no-ui         # boot check: wait for "[DEV] server listening at", then kill
   ```
   With AI Gateway credentials present (`.env.local` after `npx eve link`),
   also exercise the tool through the live model: `npx eve dev`, then ask the
   agent something that triggers it. Without credentials, say so explicitly
   in your report instead of skipping silently.
   If discovery misses the tool: wrong directory, wrong casing, or a missing
   default export. Read the diagnostics `eve info` prints.

5. **Commit** the tool and its test together as one conventional commit
   (e.g. `feat(<agent>): add <tool_name> tool`).
