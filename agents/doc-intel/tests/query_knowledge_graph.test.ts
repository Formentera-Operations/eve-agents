import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

const queryKnowledgeGraph = (await import("../agent/tools/query_knowledge_graph.ts")).default;

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

test("returns answer, sources, and the verification reminder", async () => {
  globalThis.fetch = async () =>
    Response.json({
      answer: "Benbrook D Fed 3H has 12 documents across 5 classes.",
      sources: ["FP GRIFFIN/BENBROOK UNIT 'D' FED 3H/Drilling/x.pdf"],
      mode: "GRAPH_COMPLETION",
    });
  const result = await queryKnowledgeGraph.execute(
    { question: "Everything on Benbrook D Fed 3H" },
    {} as never,
  );
  assert.ok(!("error" in result));
  assert.equal(result.sources.length, 1);
  assert.match(String(result.reminder), /document-level/);
});

test("passes evidence_doc_ids through and tolerates their absence", async () => {
  globalThis.fetch = async () =>
    Response.json({
      answer: "Liberty fraced S617HF.",
      sources: ["WESTLAKE RESOURCES/BULL MOUNTAIN-31-18-DIV S617HF/Completions/Frac/r.pdf"],
      evidence_doc_ids: ["2026-05-31-report-bull-mountain-36438031-ab12cd34"],
      mode: "GRAPH_COMPLETION",
    });
  const result = await queryKnowledgeGraph.execute({ question: "Q" }, {} as never);
  assert.ok(!("error" in result));
  assert.deepEqual(result.evidence_doc_ids, ["2026-05-31-report-bull-mountain-36438031-ab12cd34"]);
  assert.match(String(result.reminder), /read_evidence/);
});

test("degrades gracefully when the graph service is unreachable", async () => {
  globalThis.fetch = async () => {
    throw new Error("ECONNREFUSED");
  };
  const result = await queryKnowledgeGraph.execute({ question: "Q" }, {} as never);
  assert.ok("error" in result);
  assert.match(String(result.error), /not reachable/);
  assert.match(String(result.error), /graph memory was unavailable/);
});

test("rejects malformed service responses", async () => {
  globalThis.fetch = async () => Response.json({ nope: true });
  const result = await queryKnowledgeGraph.execute({ question: "Q" }, {} as never);
  assert.ok("error" in result);
  assert.match(String(result.error), /unexpected shape/);
});
