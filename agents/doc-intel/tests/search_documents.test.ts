import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

const dir = mkdtempSync(join(tmpdir(), "search-"));
writeFileSync(
  join(dir, "m.csv"),
  [
    "key,asset_team,well,category,entry_type,well_name_meta,bytes,parse_source,parsed_ref",
    "FP GRIFFIN/ALPHA 1H/Financial/AFE/a.pdf,FP GRIFFIN,ALPHA 1H,Financial/AFE,AFE,,10,pilot-tierA,s3://d/r/0.json",
    "FP GRIFFIN/BETA 2H/Drilling/Daily/b.pdf,FP GRIFFIN,BETA 2H,Drilling/Daily,Daily Report (Drilling),,10,unparsed,",
    "WESTLAKE RESOURCES/GAMMA 3/Financial/AFE/c.pdf,WESTLAKE RESOURCES,GAMMA 3,Financial/AFE,AFE,,10,pilot-tierB,s3://d/r/1.json",
  ].join("\n"),
);
process.env.WELLDRIVE_MANIFEST = join(dir, "m.csv");

const searchDocuments = (await import("../agent/tools/search_documents.ts")).default;

test("filters by entry_type and asset_team together", async () => {
  const result = await searchDocuments.execute(
    { entry_type: "AFE", asset_team: "FP GRIFFIN", limit: 25 },
    {} as never,
  );
  assert.equal(result.total_matches, 1);
  assert.equal(result.documents[0].well, "ALPHA 1H");
});

test("well filter is case-insensitive substring", async () => {
  const result = await searchDocuments.execute({ well: "gamma", limit: 25 }, {} as never);
  assert.equal(result.total_matches, 1);
  assert.equal(result.documents[0].asset_team, "WESTLAKE RESOURCES");
});

test("limit caps returned rows but reports true match count", async () => {
  const result = await searchDocuments.execute({ limit: 1 }, {} as never);
  assert.equal(result.total_matches, 3);
  assert.equal(result.returned, 1);
  assert.equal(result.documents.length, 1);
});
