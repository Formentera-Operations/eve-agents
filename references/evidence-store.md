# Evidence store (LiteParse + LanceDB)

doc-intel's third retrieval leg: the corpus parsed into page-keyed layers —
page text, JPEG page screenshots, extracted figures — stored with text and
image embeddings in an application-owned LanceDB database, searched
mechanically at query time. Interpretation happens at read time in the agent
loop; the knowledge graph (see `graph-export.md`) interprets once at ingest.

Coverage: the 500-file corpus sample plus the full Westlake Resources
tranche. Store lives at `agents/doc-intel/analysts/.evidence/` (gitignored,
deliberately OUTSIDE `.cognee/`, which graph rebuilds wipe); versioned
snapshots publish to the derived bucket. That path is a symlink — the bytes
physically live at `~/.doc-intel/evidence/` (likewise `.cognee` →
`~/.doc-intel/cognee/`), because eve's dev runtime copies the whole agent
directory on every `eve dev` launch with a hard-coded skip list that
ignores `.gitignore` (eve 0.19; a 66 GB snapshot per launch otherwise).

## The three legs, divided

| Leg | Recalls | Ask it | Interpretation happens |
|---|---|---|---|
| Manifest tools (`corpus_overview`, `search_documents`, …) | corpus structure — what exists, entry types, parse status | "what frac tickets exist for well X" | never — it's metadata |
| Knowledge graph (`query_knowledge_graph`) | what the corpus *means* — entities and relationships across the 311 graph-ingested docs | "which wells share a vendor" | once, at graph ingest |
| Evidence store (`search_evidence`, `grep_evidence`, `find_evidence_files`, `read_evidence`) | what the corpus *says* — pages, exact strings, figures | "which pages discuss stuck pipe near 9,800 ft" | at read time, in the agent loop |

## Schema (five page-keyed LanceDB tables)

Identity: `doc_id` = slugged filename stem + 8-char key hash (colon- and
slash-free); `page_id = {doc_id}:p{page_num}`. Every row carries its corpus
`s3key`, so any hit maps straight back to provenance.

- **documents** — `doc_id`, `s3key`, `asset_team`, `format_gate`
  (pdf | text | image), `page_count`
- **pages** — `page_id`, identity columns, full page `text`, gateway text
  `vector` (1536-d), CLIP `clip_vector` (512-d), `has_screenshot`,
  `screenshot` (JPEG bytes), `width`, `height`
- **chunks** — `chunk_id` (`{page_id}:c{n}`), identity columns, ~1,200-char
  page-bounded `text`, gateway `vector`
- **assets** — extracted figures / standalone images: `asset_id`, identity
  columns, `kind`, `image` (JPEG bytes), `clip_vector`
- **ledger** — per-document ingest state: `checksum` (S3 ETag or sha256),
  `status` (complete | skipped | failed), `reason`, row counts,
  `updated_at`. Terminality is explicit: `skipped` rows are deliberate
  format-gate verdicts that keep their checksum (terminal for those exact
  bytes); `failed` rows — fetch or parse errors — are written with **no
  checksum**, count as failures in reports, and re-run every pass. Skips
  are queryable, never silent.

Version-pin divergences from the reference implementation
(`lancedb/liteparse-lancedb-pdf-qa`), forced by lancedb==0.34.0 (cognee's
resolution): image columns are plain `large_binary`, not
`lance-encoding:blob` (`take_blobs` panics); grep uses `regexp_like` filter
pushdown, not a raw column scan (also panics at scale). Query paths must
SELECT image columns away unless bytes were explicitly requested.

## Format gates (KTD4) and Option B

- **PDF** — full layers via LiteParse: page text, JPEG screenshots
  (quality 70, max 2,200 px, measured 84–266 KB/page), figures, raw parse
  JSON incl. text-item bounding boxes retained under
  `.evidence/parsed/<doc_id>/` for later visual-citation work.
- **Text-native (LAS/CSV/TXT)** — one logical page carrying the full
  (2M-char-capped) text; only the first **50 chunks embed** (R10 Option B,
  Rob 2026-07-07 — sample LAS files averaged 728 chunks/doc). Grep and
  page reads see the full text; only deep-row semantic granularity is
  traded away.
- **Standalone images (PNG/JPG/TIF)** — screenshot record + CLIP vector,
  no text.
- **Excel family, XML, EML, ZIP, KDEX** — ledgered skips (v1 scope
  boundary; separate follow-up decision).

## Retrieval

Modes: `chunks` / `pages` / `fts` (BM25) / `images` (CLIP over page
screenshots) / `assets` (CLIP over figures) / `hybrid_bundle` (default) —
the searches run together and merge by `page_id`, each page winning on its
strongest signal (best-rank reciprocal score; cross-signal agreement is
only a tie-break). Grep is a true substring/regex scan pushed into the
query engine — never FTS-gated, because BM25 tokenization silently drops
codes like `S733H`.

Answer-time vision (R7): `read_evidence` with a `question` sends the stored
page screenshot to gateway vision **inside the analysts service** and
returns a text finding with its page citation. eve 0.19 cannot put images
in front of its model (`decisions/2026-07-06-evidence-read-vision-mechanism.md`);
screenshot bytes never transit the seam. Vision model:
`anthropic/claude-sonnet-5` (Haiku misread small log annotations in live
testing; `EVIDENCE_VISION_MODEL` overrides).

## Egress discipline

Text embeddings and vision go through the Vercel AI Gateway only — the
config guard (`evidence/config.py`) refuses to initialize against any other
endpoint (host equality, shared with the graph leg's guard). Image
embeddings are local OpenCLIP (`ViT-B-32-quickgelu`/openai, MPS-accelerated
when available); its pretrained weights fetch once at setup
(`prefetch_clip_weights`) — model weights, never document content. The raw
corpus bucket is read-only to this package.

## Regeneration

The store is fully rebuildable from raw corpus + manifest — snapshots are
convenience, not the durability story. From `agents/doc-intel/analysts/`:

```bash
# sample (manifest mode; checksum = sha256 of bytes)
uv run python -m doc_intel_analysts.evidence.ingest \
    --manifest ../../../corpus/sample-manifest.csv

# Westlake (prefix mode; checksum = S3 ETag, no re-fetch of completed docs)
uv run python -m doc_intel_analysts.evidence.ingest --prefix "WESTLAKE RESOURCES/"
```

Ingest is ledger-driven, resumable, and idempotent: re-runs process only
new/changed/failed documents, and each pass starts by sweeping orphaned
rows from any crash-interrupted first-seen ingest (`reconcile_orphans`).
Parse and fetch failures are retriable by construction — recorded as
`failed` with no checksum. That is a PR #12 fix: before it they were
ledgered as terminal skips and never re-ran (see
`../docs/solutions/logic-errors/ingest-ledger-conflates-parse-failures-with-skips.md`).
Direct (manifest-mode) passes end with FTS/BTree index builds and MVCC
compaction (`store.optimize()` — delete-before-insert accumulates dead
versions otherwise); batch mode (`--max-new N`, how Westlake runs) always
defers maintenance to its own invocation — light documents/ledger
compaction mid-pass (`--maintain --light`), one full `--maintain` at end
of pass. Concurrent service reads during ingest writes are safe (MVCC;
verified). One rule: never run two ingest processes against the same
store. Long runs need a fresh gateway token per ~12 h (`npx vercel env pull`
in `agents/doc-intel/`).

Retrieval benchmark (R8-approved label set at `benchmark/evidence-questions.json`):

```bash
uv run python -m doc_intel_analysts.evidence.benchmark \
    --questions ../../../benchmark/evidence-questions.json
```

## Snapshots (R12)

```bash
uv run python -m doc_intel_analysts.evidence.snapshot publish
uv run python -m doc_intel_analysts.evidence.snapshot restore --stamp <stamp> --dest <dir>
```

Publishes the whole Lance dataset (blobs included) to
`s3://formentera-welldrive-derived/runs/doc-intel/evidence/<stamp>/` with a
`_snapshot.json` manifest; restore downloads to a usable lance root.
Cadence: after each gated ingest phase, not continuous.

## Known limitations

- Ultra-tall log-strip TIFs (e.g. CBL prints) become unreadable thumbnails
  under the max-dimension bound — a tiling policy is future work.
- Figure pages are text-sparse, so text search cannot rank them; the
  working figure path is `find_evidence_files` → `read_evidence` with a
  question. Retrieval-layer figure metrics reflect this honestly.
- `assets` is empty for PDFs at LiteParse's default `image_mode`; figure
  capability rides page screenshots + vision in v1.
- No image-only table question exists in the sample benchmark (LiteParse
  OCR captured every printed form); one is to be drawn from the Westlake
  store.
