import { defineEval } from "eve/evals";
import { includes } from "eve/evals/expect";

// Exercises the full eve → delegate_analysis → deepagents analyst path.
// Requires the analyst service running (uvicorn on :8734, see README) and
// AI Gateway credentials — this eval is NOT part of the credential-free bar.
export default defineEval({
  description:
    "Cross-AFE synthesis via the analyst service: the agent must delegate and return verified figures.",
  async test(t) {
    await t.send(
      "Using your delegate_analysis analyst service, compare the AFEs for Courts Federal 1H, David William 8H, and Atlas J.J. 4H: which has the highest total gross estimate?",
    );
    t.succeeded();
    t.calledTool("delegate_analysis");
    t.check(t.reply, includes("3,469,300"));
    t.check(t.reply, includes("Atlas"));
  },
});
