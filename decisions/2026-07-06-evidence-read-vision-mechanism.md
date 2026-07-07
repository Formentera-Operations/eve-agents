# Evidence store: answer-time vision is service-side, not model-side

**Decision:** `read_evidence` implements R7 (answer-time page vision) service-side.
The eve tool accepts an optional `question`; when present, the analysts service
sends the stored page screenshot to gateway vision itself and returns a text
finding with the page citation. Screenshot bytes never cross the eve tool
boundary.

**Context:** The evidence-store plan (KTD10) required a spike against eve 0.19
before any screenshot work, because whether the eve model can consume a
tool-returned image was unproven.

**Spike evidence (2026-07-06, eve 0.19 installed source):**

- `ToolModelOutput` (`eve/dist/src/shared/tool-definition.d.ts`) is a closed
  union: `{type: "text"}` | `{type: "json"}`. No content/media variant, unlike
  the AI SDK's `ToolResultOutput` it is otherwise modeled on.
- The runtime enforces the narrowing, it isn't just types:
  `eve/dist/src/harness/tools.js` throws
  `TypeError('Expected tool model output type to be "text" or "json".')` for
  any other shape, and tool `execute` returns must be JSON-serializable.

So a doc-intel tool cannot put a page image in front of the eve model in 0.19.

**Alternatives considered:**

- *Model-side vision (tool returns the image):* impossible under the runtime
  contract above. Re-evaluate only if a future eve release adds a media
  variant to `ToolModelOutput`.
- *Data-URL-in-JSON smuggling:* the model would receive it as text, not
  pixels; also bloats tool output far past sane sizes. Rejected.

**Trade-offs accepted:** The vision model call happens inside the analysts
service (same gateway, same egress point), so the eve agent reasons over a
text finding rather than raw pixels. That is one interpretation step removed
from the agent loop, but keeps the provenance discipline: the finding carries
its page_id and S3 key, and the screenshot stays retrievable from the store
for humans.

**Consequences:** Fixes the `read_evidence` contract before U2 rendering work
(per the plan): `read` returns page text always; `question` triggers the
service-side vision read; no image payloads in any eve tool schema.
