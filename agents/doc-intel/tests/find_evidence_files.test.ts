import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

const findEvidenceFiles = (await import("../agent/tools/find_evidence_files.ts")).default;

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

test("returns matching documents", async () => {
  let requestBody: unknown;
  globalThis.fetch = async (_url, init) => {
    requestBody = JSON.parse(String(init?.body));
    return Response.json({
      documents: [
        {
          doc_id: "cement-bond-ab12cd34",
          s3key: "WESTLAKE RESOURCES/WELL/cement bond.pdf",
          asset_team: "WESTLAKE RESOURCES",
          format_gate: "pdf",
          page_count: 12,
        },
      ],
    });
  };
  const result = await findEvidenceFiles.execute(
    { name_query: "cement bond", asset_team: "WESTLAKE RESOURCES" },
    {} as never,
  );
  assert.ok(!("error" in result));
  assert.equal(result.documents[0].format_gate, "pdf");
  assert.deepEqual(requestBody, {
    name_query: "cement bond",
    asset_team: "WESTLAKE RESOURCES",
  });
});

test("degrades gracefully when the evidence service is unreachable", async () => {
  globalThis.fetch = async () => {
    throw new Error("ECONNREFUSED");
  };
  const result = await findEvidenceFiles.execute({}, {} as never);
  assert.ok("error" in result);
  assert.match(String(result.error), /not reachable/);
});

test("rejects malformed service responses", async () => {
  globalThis.fetch = async () => Response.json({ files: [] });
  const result = await findEvidenceFiles.execute({}, {} as never);
  assert.ok("error" in result);
  assert.match(String(result.error), /unexpected shape/);
});
