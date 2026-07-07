import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

const readEvidence = (await import("../agent/tools/read_evidence.ts")).default;

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

const pageBody = {
  page_id: "log-ab12cd34:p2",
  doc_id: "log-ab12cd34",
  page_num: 2,
  s3key: "TEAM/WELL/log.pdf",
  asset_team: "TEAM",
  text: "GR track shows...",
  has_screenshot: true,
};

test("returns page text without vision when no question is asked", async () => {
  globalThis.fetch = async () => Response.json(pageBody);
  const result = await readEvidence.execute(
    { page_id: "log-ab12cd34:p2" },
    {} as never,
  );
  assert.ok(!("error" in result));
  assert.ok("text" in result);
  assert.equal(result.text, "GR track shows...");
  assert.equal(result.vision_finding, undefined);
});

test("returns a vision finding with citation when a question is asked", async () => {
  globalThis.fetch = async () =>
    Response.json({
      ...pageBody,
      vision_finding: "The gamma ray curve peaks at 9,810 ft.",
      vision_citation: { s3key: "TEAM/WELL/log.pdf", page: 2 },
    });
  const result = await readEvidence.execute(
    { page_id: "log-ab12cd34:p2", question: "Where does the GR curve peak?" },
    {} as never,
  );
  assert.ok(!("error" in result));
  assert.ok("vision_finding" in result);
  assert.match(String(result.vision_finding), /9,810 ft/);
  assert.equal(result.vision_citation?.page, 2);
});

test("returns whole-document reads", async () => {
  globalThis.fetch = async () =>
    Response.json({
      doc_id: "log-ab12cd34",
      s3key: "TEAM/WELL/log.pdf",
      pages: [{ page_id: "log-ab12cd34:p1", page_num: 1, text: "cover" }],
    });
  const result = await readEvidence.execute(
    { doc_id: "log-ab12cd34" },
    {} as never,
  );
  assert.ok(!("error" in result));
  assert.ok("pages" in result);
  assert.equal(result.pages.length, 1);
});

test("maps 404 to a usable hint", async () => {
  globalThis.fetch = async () => new Response("{}", { status: 404 });
  const result = await readEvidence.execute({ page_id: "nope:p1" }, {} as never);
  assert.ok("error" in result);
  assert.match(String(result.error), /Unknown page_id/);
});

test("degrades gracefully when the evidence service is unreachable", async () => {
  globalThis.fetch = async () => {
    throw new Error("ECONNREFUSED");
  };
  const result = await readEvidence.execute({ page_id: "x:p1" }, {} as never);
  assert.ok("error" in result);
  assert.match(String(result.error), /not reachable/);
});

test("rejects malformed service responses", async () => {
  globalThis.fetch = async () => Response.json({ nope: true });
  const result = await readEvidence.execute({ page_id: "x:p1" }, {} as never);
  assert.ok("error" in result);
  assert.match(String(result.error), /unexpected shape/);
});
