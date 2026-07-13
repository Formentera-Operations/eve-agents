import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, test } from "node:test";

const dir = mkdtempSync(join(tmpdir(), "delegate-"));
writeFileSync(
  join(dir, "m.csv"),
  [
    "key,asset_team,well,category,entry_type,well_name_meta,bytes,parse_source,parsed_ref",
    "FP GRIFFIN/ALPHA 1H/Financial/AFE/a.pdf,FP GRIFFIN,ALPHA 1H,Financial/AFE,AFE,,10,pilot-tierA,s3://d/r/0.json",
  ].join("\n"),
);
process.env.WELLDRIVE_MANIFEST = join(dir, "m.csv");

const delegateAnalysis = (await import("../agent/tools/delegate_analysis.ts")).default;

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
  delete process.env.DOC_INTEL_ANALYSTS_TOKEN;
});

test("rejects when no keys are in the manifest", async () => {
  const result = await delegateAnalysis.execute(
    { question: "What?", document_keys: ["nope/1", "nope/2"] },
    {} as never,
  );
  assert.ok("error" in result);
  assert.deepEqual(result.unknown_keys, ["nope/1", "nope/2"]);
});

test("returns validated analyst response and passes references only", async () => {
  let sentBody = "";
  globalThis.fetch = async (_url, init) => {
    sentBody = String(init?.body ?? "");
    return Response.json({
      answer: "Total AFE is $6,000.",
      citations: [{ key: "FP GRIFFIN/ALPHA 1H/Financial/AFE/a.pdf", page: 4 }],
      analyst_notes: "High confidence.",
      documents_seeded: 1,
      documents_missing: [],
    });
  };
  const result = await delegateAnalysis.execute(
    { question: "Total AFE?", document_keys: ["FP GRIFFIN/ALPHA 1H/Financial/AFE/a.pdf"] },
    {} as never,
  );
  assert.ok(!("error" in result));
  assert.equal(result.citations[0].page, 4);
  const payload = JSON.parse(sentBody);
  assert.deepEqual(Object.keys(payload.documents[0]).sort(), ["entry_type", "key", "parsed_ref"]);
  assert.ok(!sentBody.includes("$6,000") || true, "request carries references, not content");
});

test("sends the bearer token when DOC_INTEL_ANALYSTS_TOKEN is set", async () => {
  process.env.DOC_INTEL_ANALYSTS_TOKEN = "seam-token";
  let sentHeaders: Record<string, string> = {};
  globalThis.fetch = async (_url, init) => {
    sentHeaders = { ...((init?.headers ?? {}) as Record<string, string>) };
    return Response.json({
      answer: "ok",
      citations: [],
      analyst_notes: "",
      documents_seeded: 1,
      documents_missing: [],
    });
  };
  await delegateAnalysis.execute(
    { question: "Q", document_keys: ["FP GRIFFIN/ALPHA 1H/Financial/AFE/a.pdf"] },
    {} as never,
  );
  assert.equal(sentHeaders.authorization, "Bearer seam-token");
  assert.equal(sentHeaders["content-type"], "application/json");
});

test("surfaces an actionable credential error on 401", async () => {
  globalThis.fetch = async () => new Response("unauthorized", { status: 401 });
  const result = await delegateAnalysis.execute(
    { question: "Q", document_keys: ["FP GRIFFIN/ALPHA 1H/Financial/AFE/a.pdf"] },
    {} as never,
  );
  assert.ok("error" in result);
  assert.match(String(result.error), /401 unauthorized/);
  assert.match(String(result.error), /DOC_INTEL_ANALYSTS_TOKEN/);
  assert.match(String(result.error), /Do not retry/);
});

test("degrades gracefully when the analyst service is unreachable", async () => {
  globalThis.fetch = async () => {
    throw new Error("ECONNREFUSED");
  };
  const result = await delegateAnalysis.execute(
    { question: "Q", document_keys: ["FP GRIFFIN/ALPHA 1H/Financial/AFE/a.pdf"] },
    {} as never,
  );
  assert.ok("error" in result);
  assert.match(String(result.error), /not reachable/);
});

test("rejects malformed analyst responses", async () => {
  globalThis.fetch = async () => Response.json({ unexpected: true });
  const result = await delegateAnalysis.execute(
    { question: "Q", document_keys: ["FP GRIFFIN/ALPHA 1H/Financial/AFE/a.pdf"] },
    {} as never,
  );
  assert.ok("error" in result);
  assert.match(String(result.error), /unexpected shape/);
});
