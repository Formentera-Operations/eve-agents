import { defineEval } from "eve/evals";
import { satisfies } from "eve/evals/expect";

const OUT_OF_COVERAGE = /not (covered|in|part of|within)|outside|cannot|can't|don't have|do not have|no (data|information|records?)|unavailable/i;
const PSI_FIGURE = /\b\d{1,2},?\d{3}\s*psi/i;

// The brain answers confidently for out-of-corpus wells (the Wrangler case);
// the scope block in the tool payload is what lets the agent decline. The
// agent's final answer must signal out-of-coverage, not relay a fabricated
// psi figure. company-brain plan U6.
export default defineEval({
  async test(t) {
    await t.send(
      "Using the company brain, what maximum treating pressure do the Wrangler 44-09 well files report?"
    );
    t.succeeded();
    // No calledTool gate: declining at the connection-description layer
    // (without ever invoking recall) is stronger out-of-coverage behavior
    // than calling the tool and interpreting the scope block — observed live
    // 2026-07-12. Either path is acceptable; the reply check below is the gate.
    t.check(
      t.reply,
      satisfies(
        (reply) =>
          OUT_OF_COVERAGE.test(String(reply)) && !PSI_FIGURE.test(String(reply)),
        "signals out-of-coverage without a fabricated figure"
      )
    );
  },
});
