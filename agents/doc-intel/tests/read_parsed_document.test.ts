import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

const dir = mkdtempSync(join(tmpdir(), "readparsed-"));
writeFileSync(
  join(dir, "m.csv"),
  [
    "key,asset_team,well,category,entry_type,well_name_meta,bytes,parse_source,parsed_ref",
    "FP GRIFFIN/CBL 1/Drilling/Casing/x.tif,FP GRIFFIN,CBL 1,Drilling/Casing,CBL,,10,pilot-failed,",
  ].join("\n"),
);
process.env.WELLDRIVE_MANIFEST = join(dir, "m.csv");

const readParsedDocument = (await import("../agent/tools/read_parsed_document.ts")).default;

test("unknown key errors without touching any backend", async () => {
  const result = await readParsedDocument.execute({ key: "nope/1" }, {} as never);
  assert.ok("error" in result);
  assert.match(String(result.error), /not in the sample manifest/);
});

test("pilot-failed documents return an honest unreadable advisory", async () => {
  const result = await readParsedDocument.execute(
    { key: "FP GRIFFIN/CBL 1/Drilling/Casing/x.tif" },
    {} as never,
  );
  assert.ok("error" in result);
  assert.match(String(result.error), /failed parsing in the pilot/);
  assert.ok("entry_type" in result && result.entry_type === "CBL");
});
