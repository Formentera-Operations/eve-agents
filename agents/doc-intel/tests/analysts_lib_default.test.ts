import assert from "node:assert/strict";
import { test } from "node:test";

// Separate file on purpose: analysts_lib.test.ts loads the module with
// DOC_INTEL_ANALYSTS_URL overridden, and ESM caches one module instance per
// process. This file's process loads it with the env unset to pin the default.
const originalUrl = process.env.DOC_INTEL_ANALYSTS_URL;
delete process.env.DOC_INTEL_ANALYSTS_URL;
const { ANALYSTS_URL } = await import("../agent/lib/analysts.ts");
if (originalUrl !== undefined) {
  process.env.DOC_INTEL_ANALYSTS_URL = originalUrl;
}

test("defaults the base URL to the local analysts service when env is unset", () => {
  assert.equal(ANALYSTS_URL, "http://127.0.0.1:8734");
});
