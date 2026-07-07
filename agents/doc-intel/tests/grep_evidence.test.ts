import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

const grepEvidence = (await import("../agent/tools/grep_evidence.ts")).default;

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

test("returns exact matches with context and page identity", async () => {
  globalThis.fetch = async () =>
    Response.json({
      matches: [
        {
          page_id: "survey-ab12cd34:p1",
          doc_id: "survey-ab12cd34",
          page_num: 1,
          s3key: "TEAM/WELL S733H/survey.pdf",
          asset_team: "TEAM",
          match: "S733H",
          context: "...well S733H directional survey...",
        },
      ],
    });
  const result = await grepEvidence.execute({ pattern: "S733H" }, {} as never);
  assert.ok(!("error" in result));
  assert.equal(result.matches[0].match, "S733H");
  assert.match(String(result.reminder), /page-level/);
});

test("degrades gracefully when the evidence service is unreachable", async () => {
  globalThis.fetch = async () => {
    throw new Error("ECONNREFUSED");
  };
  const result = await grepEvidence.execute({ pattern: "S733H" }, {} as never);
  assert.ok("error" in result);
  assert.match(String(result.error), /not reachable/);
});

test("rejects malformed service responses", async () => {
  globalThis.fetch = async () => Response.json({ rows: [] });
  const result = await grepEvidence.execute({ pattern: "S733H" }, {} as never);
  assert.ok("error" in result);
  assert.match(String(result.error), /unexpected shape/);
});
