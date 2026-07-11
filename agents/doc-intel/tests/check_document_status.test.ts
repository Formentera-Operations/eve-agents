import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

const checkDocumentStatus = (await import("../agent/tools/check_document_status.ts")).default;

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

test("returns ledger matches, summary, and watermark", async () => {
  let requestBody: unknown;
  globalThis.fetch = async (_url, init) => {
    requestBody = JSON.parse(String(init?.body));
    return Response.json({
      matches: [
        {
          doc_id: "frac-summary-ab12cd34",
          s3key: "WESTLAKE RESOURCES/WELL/frac summary.xlsx",
          status: "skipped",
          reason: "excel-family deferred from v1 ingest (plan scope boundary)",
          page_count: 0,
          updated_at: "2026-07-09T04:54:00",
          will_retry: false,
        },
      ],
      summary: { complete: 0, skipped: 1, failed: 0 },
      total_matches: 1,
      ledger_as_of: "2026-07-10T16:51:27",
    });
  };
  const result = await checkDocumentStatus.execute(
    { name_query: "frac summary", asset_team: "WESTLAKE RESOURCES", status: "skipped" },
    {} as never,
  );
  assert.ok(!("error" in result));
  assert.equal(result.matches[0].status, "skipped");
  assert.equal(result.matches[0].will_retry, false);
  assert.equal(result.summary.skipped, 1);
  assert.equal(result.ledger_as_of, "2026-07-10T16:51:27");
  assert.deepEqual(requestBody, {
    name_query: "frac summary",
    asset_team: "WESTLAKE RESOURCES",
    status: "skipped",
  });
});

test("degrades gracefully when the evidence service is unreachable", async () => {
  globalThis.fetch = async () => {
    throw new Error("ECONNREFUSED");
  };
  const result = await checkDocumentStatus.execute({}, {} as never);
  assert.ok("error" in result);
  assert.match(String(result.error), /not reachable/);
  assert.match(String(result.error), /absence claims/);
});

test("surfaces non-OK service responses", async () => {
  globalThis.fetch = async () => new Response("boom", { status: 500 });
  const result = await checkDocumentStatus.execute({}, {} as never);
  assert.ok("error" in result);
  assert.match(String(result.error), /responded 500/);
});

test("rejects malformed service responses", async () => {
  globalThis.fetch = async () => Response.json({ rows: [] });
  const result = await checkDocumentStatus.execute({}, {} as never);
  assert.ok("error" in result);
  assert.match(String(result.error), /unexpected shape/);
});
