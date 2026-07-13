import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { ANALYSTS_URL, analystHeaders } from "../agent/lib/analysts.ts";

const originalToken = process.env.DOC_INTEL_ANALYSTS_TOKEN;
afterEach(() => {
  if (originalToken === undefined) {
    delete process.env.DOC_INTEL_ANALYSTS_TOKEN;
  } else {
    process.env.DOC_INTEL_ANALYSTS_TOKEN = originalToken;
  }
});

test("resolves the base URL from env with the local default", () => {
  assert.equal(
    ANALYSTS_URL,
    process.env.DOC_INTEL_ANALYSTS_URL ?? "http://127.0.0.1:8734",
  );
});

test("omits authorization when DOC_INTEL_ANALYSTS_TOKEN is unset", () => {
  delete process.env.DOC_INTEL_ANALYSTS_TOKEN;
  assert.deepEqual(analystHeaders(), { "content-type": "application/json" });
});

test("adds a bearer authorization header when DOC_INTEL_ANALYSTS_TOKEN is set", () => {
  process.env.DOC_INTEL_ANALYSTS_TOKEN = "seam-token";
  assert.deepEqual(analystHeaders(), {
    "content-type": "application/json",
    authorization: "Bearer seam-token",
  });
});
