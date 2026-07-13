import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

// ANALYSTS_URL is resolved at module load, so set the env override BEFORE a
// fresh dynamic import (same pattern as delegate_analysis.test.ts and
// WELLDRIVE_MANIFEST). The unset-env default is pinned in
// analysts_lib_default.test.ts — ESM caches one module instance per process,
// so each env state needs its own test file.
const originalUrl = process.env.DOC_INTEL_ANALYSTS_URL;
process.env.DOC_INTEL_ANALYSTS_URL = "https://analysts.example.test";
const { ANALYSTS_URL, analystHeaders, analystError } = await import(
  "../agent/lib/analysts.ts"
);
if (originalUrl === undefined) {
  delete process.env.DOC_INTEL_ANALYSTS_URL;
} else {
  process.env.DOC_INTEL_ANALYSTS_URL = originalUrl;
}

const originalToken = process.env.DOC_INTEL_ANALYSTS_TOKEN;
afterEach(() => {
  if (originalToken === undefined) {
    delete process.env.DOC_INTEL_ANALYSTS_TOKEN;
  } else {
    process.env.DOC_INTEL_ANALYSTS_TOKEN = originalToken;
  }
});

test("resolves the base URL from the DOC_INTEL_ANALYSTS_URL override", () => {
  assert.equal(ANALYSTS_URL, "https://analysts.example.test");
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

test("keeps the generic error message for non-401 statuses", () => {
  assert.equal(
    analystError("Evidence service", 500),
    "Evidence service responded 500.",
  );
  assert.equal(
    analystError("Analyst service", 503),
    "Analyst service responded 503.",
  );
});

test("returns an actionable operator message for 401", () => {
  const message = analystError("Evidence service", 401);
  assert.match(message, /^Evidence service rejected the request \(401 unauthorized\)/);
  assert.match(message, /DOC_INTEL_ANALYSTS_TOKEN/);
  assert.match(message, /operator must fix/);
  assert.match(message, /Do not retry/);
});
