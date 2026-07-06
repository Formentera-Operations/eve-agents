import { defineEval } from "eve/evals";
import { includes } from "eve/evals/expect";

// Exercises the eve → query_knowledge_graph → cognee graph path (plan U7).
// Requires the analysts service running with an ingested graph, plus AI
// Gateway credentials — NOT part of the credential-free bar.
export default defineEval({
  description:
    "Entity-shaped exploration answers from the knowledge graph with document-key provenance.",
  async test(t) {
    await t.send(
      "Using the knowledge graph, what do we know about the Wildcat Hollow S516HF well — what work was done and which service company performed the frac?",
    );
    t.succeeded();
    t.calledTool("query_knowledge_graph");
    t.check(t.reply, includes("Liberty"));
    t.check(t.reply, includes("WILDCAT HOLLOW"));
  },
});
