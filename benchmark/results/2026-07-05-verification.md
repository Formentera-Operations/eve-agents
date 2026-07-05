# 2026-07-05 — Independent adversarial verification: PASSING

Fresh-context verifier; inputs: fresh GitHub clone, benchmark, live endpoint.

- Scored 24/25 (q04 stalled on a clarifying question; correct on re-ask —
  addressed in instructions.md the same day). 25/25 reproducible.
- 20 citations verified against pilot parse JSONs in S3: zero fabricated,
  zero wrong-page. Trap answers (net vs gross, casing vs tubing, subtotal
  vs line item, proposed vs actual TMD) all correctly avoided.
- Fabrication probes 5/5 clean refusals (nonexistent wells, unreadable
  log-image TIFs, wrong-document-type asks).
- Fresh-clone mechanical bar: install + typecheck + 18/18 tests + eve info
  all green in ~6 seconds.
- House rules: no hard-coded classifiers, no credentials in code, egress
  limited to S3 → agent → local analyst service → Vercel AI Gateway.
