import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

const searchEvidence = (await import("../agent/tools/search_evidence.ts")).default;

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

const hit = {
  page_id: "report-abc12345:p3",
  doc_id: "report-abc12345",
  page_num: 3,
  s3key: "TEAM/WELL/Drilling/report.pdf",
  asset_team: "TEAM",
  score: 0.0421,
  signals: { chunks: 1, images: 4 },
  snippet: "Stuck pipe at 9800 ft...",
};

test("returns page-keyed hits with the citation reminder", async () => {
  let requestBody: unknown;
  globalThis.fetch = async (_url, init) => {
    requestBody = JSON.parse(String(init?.body));
    return Response.json({ hits: [hit], mode: "hybrid_bundle" });
  };
  const result = await searchEvidence.execute(
    { query: "stuck pipe near 9800 ft", asset_team: "TEAM" },
    {} as never,
  );
  assert.ok(!("error" in result));
  assert.equal(result.hits[0].page_id, "report-abc12345:p3");
  assert.match(String(result.reminder), /page-level/);
  assert.deepEqual(requestBody, {
    query: "stuck pipe near 9800 ft",
    asset_team: "TEAM",
  });
});

test("degrades gracefully when the evidence service is unreachable", async () => {
  globalThis.fetch = async () => {
    throw new Error("ECONNREFUSED");
  };
  const result = await searchEvidence.execute({ query: "q" }, {} as never);
  assert.ok("error" in result);
  assert.match(String(result.error), /not reachable/);
  assert.match(String(result.error), /evidence search was unavailable/);
});

test("rejects malformed service responses", async () => {
  globalThis.fetch = async () => Response.json({ nope: true });
  const result = await searchEvidence.execute({ query: "q" }, {} as never);
  assert.ok("error" in result);
  assert.match(String(result.error), /unexpected shape/);
});
