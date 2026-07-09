import { defineEval } from "eve/evals";
import { includes, satisfies } from "eve/evals/expect";

// Locks in the PR #15 coverage self-model fixes, distilled from a live
// three-run session (2026-07-09): the agent must find a real incident via
// the evidence store, claim its negative at indexed-Westlake-tranche scale
// (never sample scale), and carve out the deferred-format files honestly.
// Requires the analysts service running (uvicorn on :8734) with the FULL
// Westlake tranche ingested — the incident document is not in the 500-file
// sample — plus AI Gateway credentials. NOT part of the credential-free bar.
export default defineEval({
  description:
    "Westlake content search finds the real stuck-pipe incident and scopes its negative to indexed coverage.",
  async test(t) {
    await t.send(
      "Which pages discuss casing problems or stuck pipe on Westlake wells? Cite pages.",
    );
    t.succeeded();
    t.calledTool("search_evidence");
    t.calledTool("grep_evidence");
    // The real incident (Wildcat Hollow drillout, tubing stuck at 9,020 ft)
    // lives only in the full tranche — semantic search must surface it.
    t.check(t.reply, includes(/wildcat hollow/i));
    t.check(t.reply, includes(/9,?020/));
    // Negatives must be scoped honestly: the deferred-format carve-out
    // (spreadsheets/email were never indexed) has to be stated.
    t.check(t.reply, includes(/spreadsheet|deferred[- ]format/i));
    // The pre-fix failure mode: treating Westlake as a 125-doc sample and
    // deferring to the 111k-file archive for content it already holds.
    // Two gates: the sample-scale tell (111k / 111,000 in any casing or
    // punctuation), and any "full archive" framing — the instructions
    // forbid referring Westlake askers to the full archive at all.
    t.check(
      t.reply,
      satisfies(
        (reply) => !/111[,.]?\s?(k|000)/i.test(String(reply)),
        "never frames the corpus at 111k sample scale",
      ),
    );
    t.check(
      t.reply,
      satisfies(
        (reply) => !/full\s+archive/i.test(String(reply)),
        "does not defer to the full archive for Westlake content",
      ),
    );
  },
});
