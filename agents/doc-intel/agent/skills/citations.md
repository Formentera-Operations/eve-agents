---
description: Use when writing any answer that states a fact from a corpus document — every factual claim needs a verifiable citation.
---

# Citation discipline

Every factual claim from the corpus cites its source as:

> (S3 key, page N)

using the page numbers returned by `read_parsed_document` — never estimated
page numbers. For tier-A extraction documents, use the page numbers in
`field_page_citations` for the specific field you are quoting.

Rules:

- A claim you did not read on a returned page does not get cited — it gets
  removed, or you go read the page.
- Cross-document synthesis cites each contributing document separately.
- If two documents disagree, present both with citations; do not silently
  pick one.
- Quote short key figures verbatim (numbers, dates, names) rather than
  paraphrasing them.
- An answer you cannot ground in a readable page is "not found in the
  corpus sample" — that is always a better answer than a plausible guess.
