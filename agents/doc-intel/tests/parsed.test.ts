import assert from "node:assert/strict";
import { test } from "node:test";

import { normalizeParsed } from "../agent/lib/parsed.ts";

test("normalizes a parse run into page-addressed markdown", () => {
  const view = normalizeParsed({
    object: "parse_run",
    output: {
      chunks: [
        {
          object: "chunk",
          type: "page",
          content: "# BHA Summary\n\nAPI/UWI 4243933854",
          metadata: { pageRange: { start: 1, end: 1 } },
        },
        {
          object: "chunk",
          type: "page",
          content: "## Run 2\n\nBit depth 7,912 ft",
          metadata: { pageRange: { start: 2, end: 2 } },
        },
      ],
    },
  });
  assert.equal(view.kind, "markdown");
  assert.equal(view.pageCount, 2);
  assert.equal(view.pages[1].page, 2);
  assert.match(view.pages[1].markdown, /7,912 ft/);
});

test("normalizes an extract run into fields with page citations", () => {
  const view = normalizeParsed({
    object: "extract_run",
    output: {
      value: { afe_number: "52955", well_name: "SELMA GOODNIGHT 2H" },
      metadata: {
        afe_number: { citations: [{ page: { number: 4 } }] },
        well_name: { citations: [{ page: { number: 1 } }, { page: { number: 4 } }] },
      },
    },
  });
  assert.equal(view.kind, "extraction");
  assert.equal(view.extraction?.fields.afe_number, "52955");
  assert.deepEqual(view.extraction?.fieldPages.well_name, [1, 4]);
  assert.equal(view.pageCount, 4);
});

test("degrades gracefully on an unrecognized payload", () => {
  const view = normalizeParsed({ something: "else" });
  assert.equal(view.pageCount, 0);
  assert.deepEqual(view.pages, []);
});
