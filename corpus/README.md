# Corpus: WellDrive 500-file sample

`sample-manifest.csv` is the working set for the doc-intel agent: a
deterministic (seed=42) stratified sample of 500 files from the
`formentera-welldrive` S3 bucket (111,288 objects, three asset teams).

## Composition

- **341 pilot rows** — the June 2026 parsing pilot (6 files per entry_type,
  59 entry_types). Parsed outputs already exist under
  `s3://formentera-welldrive-derived/runs/pilot/tier{A,B,C}/` and are
  referenced by `parsed_ref`:
  - tier A: structured field extraction JSON with per-field page citations
  - tier B/C: page-chunked structured Markdown (`chunks[].type == "page"`)
- **159 fresh rows** — stratified across asset teams (40% South Texas,
  40% Westlake, 20% Griffin), `parse_source=unparsed`. Parsed on demand and
  cached to `s3://formentera-welldrive-derived/runs/doc-intel/parsed/`.

## Columns

`key` (S3 key in `formentera-welldrive`), `asset_team`, `well`, `category`
(WellDrive folder path), `entry_type` (from S3 object metadata — the
authoritative triage signal), `well_name_meta`, `bytes`, `parse_source`
(`pilot-tierA|B|C`, `pilot-failed`, `pilot-skipped`, `unparsed`),
`parsed_ref` (S3 URI of the cached parse, when one exists).

## Known-unparseable formats

The pilot proved these fail structured parsing: log-image TIFs (CBL, open/
cased hole, LWD), and vendor binaries (`.cgm`, `.pds`, `.out`, `.ndg`,
`.mlg`, `.ml6`, `.cmt`). The agent must triage these from `entry_type` +
format and say what it can't read — never pretend to parse them.

Regenerate: `scratchpad build_sample.py` + `enrich_sample.py` (session
scripts; deterministic given the same bucket state).
