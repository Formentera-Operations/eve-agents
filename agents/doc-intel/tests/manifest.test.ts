import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

const dir = mkdtempSync(join(tmpdir(), "manifest-"));
// CRLF line endings on purpose: the real manifest is written by Python's
// csv module, which emits \r\n — parsing must not leak \r into fields.
const csv = [
  "key,asset_team,well,category,entry_type,well_name_meta,bytes,parse_source,parsed_ref",
  '"FP GRIFFIN/GOODNIGHT SELMA 2H/Financial/AFE/1005504801-GOODNIGHT,_SELMA_2H-WBS-0003.pdf.PDF",FP GRIFFIN,GOODNIGHT SELMA 2H,Financial/AFE,AFE,,,pilot-tierA,s3://formentera-welldrive-derived/runs/pilot/tierA/0000.pdf.json',
  "WESTLAKE RESOURCES/SMITH 1H/Drilling/BHA & Bits/bha.pdf,WESTLAKE RESOURCES,SMITH 1H,Drilling/BHA & Bits,BHA,SMITH 1H,12345,unparsed,",
].join("\r\n");
writeFileSync(join(dir, "m.csv"), csv);
process.env.WELLDRIVE_MANIFEST = join(dir, "m.csv");

const { loadManifest, findByKey } = await import("../agent/lib/manifest.ts");

test("parses quoted keys containing commas", () => {
  const rows = loadManifest();
  assert.equal(rows.length, 2);
  assert.match(rows[0].key, /GOODNIGHT,_SELMA_2H/);
  assert.equal(rows[0].entry_type, "AFE");
  assert.equal(rows[0].parsed_ref.startsWith("s3://"), true);
});

test("CRLF endings leave no carriage returns in the last column", () => {
  const rows = loadManifest();
  assert.equal(rows[0].parsed_ref.endsWith(".json"), true);
  assert.ok(!rows[0].parsed_ref.includes("\r"));
  assert.equal(rows[1].parsed_ref, "");
});

test("findByKey returns exact matches only", () => {
  assert.equal(findByKey("nope"), undefined);
  assert.equal(
    findByKey("WESTLAKE RESOURCES/SMITH 1H/Drilling/BHA & Bits/bha.pdf")?.parse_source,
    "unparsed",
  );
});
