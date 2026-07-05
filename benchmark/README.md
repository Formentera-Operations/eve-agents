# Doc-intel ground-truth benchmark

25 questions with verifiable citations, used to score the document-intelligence
agent against the WellDrive well-file corpus sample (`corpus/sample-manifest.csv`).

## What this measures

Given a natural-language question that names wells the way an engineer would,
the agent must locate the relevant source document(s) itself and return the
correct fact. Questions never contain S3 keys or page numbers — finding the
document is part of the task.

## How it was built

1. Every fact was taken from the **parsed pilot output** already cached under
   `s3://formentera-welldrive-derived/runs/pilot/tier{A,B,C}/` and referenced by
   the `parsed_ref` column of the manifest. No parsing service or LLM API was
   called to build this benchmark — the JSONs were downloaded with `aws s3 cp`
   and read directly.
2. Page numbers come **only** from the parse JSON, never guessed:
   - tier A (field extraction): `output.metadata.<field>.citations[].page.number`
   - tier B/C (page-chunked Markdown): `output.chunks[].metadata.pageRange.start`
3. Each fact was confirmed to live in **document content** (a value, table cell,
   or line item), not in the filename — so the agent cannot shortcut by pattern
   matching the S3 key.
4. Coverage was spread deliberately across the corpus:
   - **Asset teams (all three):** FP Griffin, Formentera South Texas, Westlake
     Resources.
   - **16 distinct documents, 9 entry types:** AFE, Frac Report, Well Test,
     PVT Report, Mud Recap, Casing Tally, Final Deviation Survey, Cement Report,
     Bit Information.

## Question-type mix (25 total)

| Type | Count | What it exercises |
|------|-------|-------------------|
| `single-doc` | 10 | One fact on one page of one document |
| `cross-doc` | 8 | Combining or comparing 2+ documents (e.g. two wells' AFEs, two wells' frac stages, two wells' well tests) |
| `table-extraction` | 7 | A value inside a table (AFE cost line item, bit-record footage, casing set depth, mud weight, PVT GOR, pipe-tally setting depth) |

## Schema (`questions.json`)

Array of objects:

```jsonc
{
  "id": "q01",                       // q01..q25
  "type": "single-doc",              // single-doc | cross-doc | table-extraction
  "question": "…",                   // natural language; no keys or page numbers
  "expected_answer": "…",            // objective, checkable value
  "citations": [                     // every key+page a human can open to verify
    { "key": "<S3 key in formentera-welldrive>", "page": 1 }
  ],
  "notes": "…"                       // how to verify + tolerance
}
```

## Grading rule

An answer scores **correct** only when **both** hold:

1. The returned answer matches `expected_answer` within the tolerance stated in
   that question's `notes` (e.g. "±1%", "±$1", "±5 ft", or equivalent units).
   For comparison/synthesis questions the agent must reach the correct
   conclusion (which is higher/lower, the difference, or the identity), not just
   restate one number.
2. **Every** `key` + `page` pair in `citations` verifiably supports the answer —
   a human opening that document at that page in the source
   (`s3://formentera-welldrive`) sees the fact. A right answer backed by a wrong
   or missing citation does **not** count as correct.

**Pass threshold: ≥ 23 / 25.**

## Reproducing / verifying a question

```bash
# 1. find the parsed JSON for a cited key
grep -F "<key>" corpus/sample-manifest.csv        # read the parsed_ref column

# 2. download and inspect it
aws s3 cp <parsed_ref> /tmp/parse.json
#   tierA: output.value.<field> + output.metadata.<field>.citations[].page.number
#   tierB/C: output.chunks[] where metadata.pageRange.start == cited page
```

To confirm the fact in the original document, open the `key` in
`s3://formentera-welldrive` at the cited page.
