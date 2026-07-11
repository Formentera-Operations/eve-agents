import { defineEval } from "eve/evals";
import { includes, satisfies } from "eve/evals/expect";

// Locks in the Wildcat Hollow DSU graph extension proven live on
// 2026-07-10 (710 docs, additive ingest, no rebuild): a second DSU's
// entity-shaped questions route graph-first, and — the extension's core
// thesis — service vendors resolve to the SAME conformed entity across
// DSUs (Liberty fracked both Wildcat Hollow 16-33 and Bull Mountain
// 31-18). Requires the analysts service running (uvicorn on :8734) with
// the Wildcat-enriched graph and AI Gateway credentials. NOT part of the
// credential-free bar.
export default defineEval({
  description:
    "Wildcat Hollow pad question: graph-first recall, cross-DSU vendor conformance, cited stage evidence.",
  async test(t) {
    await t.send(
      "Using the knowledge graph, tell me about the Wildcat Hollow 16-33 pad: which wells are on it and who performed the frac work. Did that same frac company work on the Bull Mountain pad too? Verify the most interesting claim with a page citation before presenting it.",
    );
    t.succeeded();
    // Entity-shaped -> graph-first, then page-verify graph recall through
    // the evidence store (Wildcat docs are outside the sample manifest).
    t.calledTool("query_knowledge_graph");
    t.calledTool("read_evidence");
    // The frac contractor is the pad's constant.
    t.check(t.reply, includes(/liberty/i));
    // Cross-DSU conformance: the answer must AFFIRMATIVELY connect the
    // same vendor to Bull Mountain — one graph entity spanning both DSUs.
    // A bare includes() would green-light "I cannot verify whether they
    // worked on Bull Mountain" (Codex review): require a sentence that
    // links the vendor to Bull Mountain without negation.
    t.check(
      t.reply,
      satisfies((reply) => {
        const sentences = String(reply).split(/(?<=[.!?])\s+|\n+/);
        return sentences.some((s) => {
          const l = s.toLowerCase();
          if (!l.includes("bull mountain")) return false;
          if (!l.includes("liberty")) return false;
          return !/\b(cannot|can't|could not|couldn't|unable|no evidence|not (?:verify|confirm|find|appear|work)|did not|didn't|never|unclear|unverified)\b/.test(
            l,
          );
        });
      }, "affirmatively connects the frac vendor to Bull Mountain in one sentence, without negation"),
    );
    // Well roster: recall varies run-to-run, so gate on a set — at least
    // two of the four 16-33 producers named.
    t.check(
      t.reply,
      satisfies((reply) => {
        const r = String(reply).toUpperCase();
        const wells = ["S512HF", "S516HF", "S614HF", "S618HF"];
        return wells.filter((w) => r.includes(w)).length >= 2;
      }, "names at least two of the four Wildcat Hollow 16-33 producers"),
    );
    // Real citations, not hand-waving: at least one s3key-style document
    // reference AND a page marker — naming a document without the page is
    // exactly the regression this gate exists to catch. Matches observed
    // citation styles: "page 2", "pages 1, 5-9", "(p.10)", "p. 4".
    t.check(t.reply, includes(/\.pdf/i));
    t.check(t.reply, includes(/\bpages?[ .:]*\d|\(p\.?\s?\d|\bp\.\s?\d/i));
  },
});
