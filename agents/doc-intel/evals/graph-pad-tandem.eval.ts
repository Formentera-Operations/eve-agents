import { defineEval } from "eve/evals";
import { includes, satisfies } from "eve/evals/expect";

// Locks in the cross-leg tandem proven live on 2026-07-09 after the Bull
// Mountain pilot enrichment: entity-shaped questions route graph-first,
// graph recall gets page-verified through the evidence store via the
// returned evidence_doc_ids (PR #21), and the answer carries real page
// citations. Requires the analysts service running (uvicorn on :8734)
// with the pilot-enriched graph (Bull Mountain ingested 2026-07-09) and
// AI Gateway credentials. NOT part of the credential-free bar.
export default defineEval({
  description:
    "Bull Mountain pad question: graph-first recall, evidence-store page verification, cited vendors and events.",
  async test(t) {
    await t.send(
      "Using the knowledge graph, tell me about the Bull Mountain pad: which wells are on it, which service companies worked on them and in what roles, and the most notable operational event you can find. Verify the most interesting claim with a page citation before presenting it.",
    );
    t.succeeded();
    // Entity-shaped -> graph-first, then page-verify graph recall through
    // the evidence store (these docs are outside the sample manifest).
    t.calledTool("query_knowledge_graph");
    t.calledTool("read_evidence");
    // Vendor roster: the rig and frac contractors are the pad's constants;
    // the third vendor varies with graph recall, so it gates on a set.
    t.check(t.reply, includes(/nabors/i));
    t.check(t.reply, includes(/liberty/i));
    t.check(
      t.reply,
      satisfies((reply) => {
        const r = String(reply).toLowerCase();
        return [
          "halliburton", "baroid", "ipt", "integrated petroleum",
          "total directional", "schlumberger", "certarus",
        ].some((v) => r.includes(v));
      }, "names a third service company beyond the rig and frac contractors"),
    );
    // The pad's dominant NPT event: the S617HF stage-27 wireline parting.
    t.check(t.reply, includes(/S617HF/i));
    t.check(t.reply, includes(/wireline/i));
    // Real citations, not hand-waving: at least one s3key-style document
    // reference must appear.
    t.check(t.reply, includes(/\.pdf/i));
  },
});
