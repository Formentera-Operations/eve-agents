# 2026-07-07 — R10 cost + disk checkpoint: Westlake ingest (U7)

Presented to Rob with measured sample numbers; **Rob approved Option B**
("B", 2026-07-07). This is the explicit go the plan requires before
full-tranche spend.

## Measured basis (sample store)

- PDF: 8.0 pages/doc, 31.1 chunks/doc, screenshots 84–266 KB/page (q70).
- Text-native (LAS/CSV/TXT): **728.5 chunks/doc average** — the cost and
  disk elephant; a single capped LAS file can reach ~1,900 chunks.
- Store all-in: ~330 KB/page. Local disk free at decision time: 82 GB.

## Options presented

| | Gateway cost | Store size | Notes |
|---|---|---|---|
| A — embed everything (plan literal) | ~$64 | ~131 GB | exceeds free disk; 71 GB is text-native chunk vectors alone |
| **B — text-native head embed (50 chunks/doc), full text kept for grep/read** | **~$9** | **~65 GB** | chosen — grep exactness unaffected (scans page text, not vectors) |
| C — B + JPEG q60/1800px | ~$9 | ~53 GB | rejected: vision accuracy was proven at B's settings; disk not worth the untested risk |

## Implementation levers landed with the decision

- `TEXT_NATIVE_MAX_CHUNKS = 50` (parse.py) — page rows keep full capped
  text; only deep-row semantic granularity is given up.
- CLIP on MPS (Apple GPU): measured **2.6 s/doc** on a live 50-doc
  Westlake slice vs ~25 s/doc CPU during the sample run → full tranche
  projects ~1.5–3 days wall-clock instead of ~9.
- ETag ledger short-circuit in prefix mode: resumable passes skip
  completed docs from the S3 listing alone, no re-fetch of 37k objects.

## Tranche at launch (live listing, 2026-07-07)

37,459 objects: 18,681 PDFs, 13,656 text-native, 89 images, 5,033 ledgered
skips (Excel family + deferred formats — scope boundary, visible in the
ledger). Budget approved: ~$9 gateway spend, ~65 GB local store, snapshot
to the derived bucket at completion (U8).
