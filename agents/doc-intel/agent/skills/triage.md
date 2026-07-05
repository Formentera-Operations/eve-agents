---
description: Use when deciding which documents to read, how to route a question to the right document classes, or whether a document is worth parsing.
---

# Document triage

Route by **entry_type** — the classification stored in S3 object metadata and
surfaced by every corpus tool. It is authoritative where present. Never infer
a document's class from its filename; filenames in this corpus are vendor
artifacts and lie freely.

Reason from the question to the document classes that would contain the
answer, then search by entry_type:

- Costs, spend estimates, partner interests → `AFE`, `Field Ticket`
- What happened during drilling, day by day → `Daily Report (Drilling)`,
  `Well Chronology`, `EOW Report`
- Completion and stimulation → `Frac Report`, `Completion Packet`,
  `Daily Report (Completion)`, `Flow Back Report`, `Perforation Report`
- Wellbore geometry and trajectory → `Deviation Survey`,
  `Final Deviation Survey`, `Directional Plans`, `Well Schematic`
- Fluids, mud, cement → `Mud Recap`, `Mud Program`, `Cement Program`,
  `Cement Report`, `Drilling Fluid Report`
- Reservoir and fluid properties → `PVT Report`, `Well Test`, `Core`
- Regulatory filings and permits → `Regulatory Information`, `W15`, `Plat`
- Production → `Production Information`, `PVA`, `Final PVA`

This mapping is guidance, not a rulebook — when unsure, search more than one
entry_type and let the content decide.

## What is not readable

Log-image TIFs (CBL, open/cased hole logs, LWD composites) and vendor binary
formats (`.cgm`, `.pds`, `.out`, `.ndg`, `.mlg`, `.ml6`, `.cmt`) failed
structured parsing in the pilot. `read_parsed_document` will tell you when a
document is in this bucket. Say plainly that the document exists but its
content is not machine-readable here — never fabricate content for it, and
suggest the nearest readable alternative (e.g. a `Final Geosteering
Interpretation` PDF instead of a raw LWD composite).

## Parse cost awareness

Documents with `parse_source: unparsed` trigger a paid parse on first read.
Prefer already-parsed documents (`pilot-tier*`, `doc-intel-cache`) when they
can answer the question; parse fresh documents when the question genuinely
needs them.
