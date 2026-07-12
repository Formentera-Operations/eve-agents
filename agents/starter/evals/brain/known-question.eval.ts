import { defineEval } from "eve/evals";
import { includes } from "eve/evals/expect";

// E2E proof for the hosted company-brain MCP connection (company-brain plan
// U6): the agent discovers brain__recall over HTTP+bearer and answers a known
// in-corpus question from it. Requires BRAIN_MCP_TOKEN in the environment.
export default defineEval({
  async test(t) {
    await t.send(
      "Using the company brain, which wireline company was used on the Wildcat Hollow S512HF frac stage?"
    );
    t.succeeded();
    t.calledTool("brain__recall");
    t.check(t.reply, includes(/go\s*wireline/i));
  },
});
