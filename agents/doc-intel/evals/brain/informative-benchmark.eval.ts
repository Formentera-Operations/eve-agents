import { defineEval } from "eve/evals";

// Informative smoke (company-brain plan: misses trigger agent-side debugging,
// never cutover rollback). Gates only on the brain tool actually being used.
export default defineEval({
  async test(t) {
    await t.send(
      "Per the company brain, at what pressure did the Liberty pump trip occur on the Bull Mountain wells?"
    );
    t.succeeded();
    t.calledTool("brain__recall");
    t.log(`npt3 reply: ${t.reply}`);
  },
});
