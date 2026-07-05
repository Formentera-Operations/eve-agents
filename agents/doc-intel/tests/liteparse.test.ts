import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { extensionOf, parseBytesToView, parseWithLiteParse } from "../agent/lib/liteparse.ts";

test("extensionOf handles WellDrive's messy key shapes", () => {
  assert.equal(extensionOf("A/B/REPORT.PDF_5480732.PDF"), ".pdf");
  assert.equal(extensionOf("A/B/survey.out"), ".out");
  assert.equal(extensionOf("A/B/noext"), "");
});

test("rejects vendor binary formats without touching S3", async () => {
  const result = await parseWithLiteParse("TEAM/WELL/Drilling/x.cgm");
  assert.ok("error" in result);
  assert.match(result.error, /not parseable/);
});

test("parses a real PDF into page-addressed markdown", async () => {
  const bytes = readFileSync(join(import.meta.dirname, "fixtures/fixture.pdf"));
  const view = await parseBytesToView(new Uint8Array(bytes));
  assert.equal(view.kind, "markdown");
  assert.equal(view.pageCount, 1);
  assert.equal(view.pages[0].page, 1);
  assert.match(view.pages[0].markdown, /1,234,567/);
});
