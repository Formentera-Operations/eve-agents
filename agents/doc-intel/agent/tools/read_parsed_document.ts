import { createHash } from "node:crypto";

import { defineTool } from "eve/tools";
import { z } from "zod";

import { findByKey } from "../lib/manifest.ts";
import { parseWithLiteParse } from "../lib/liteparse.ts";
import { fetchParsedRef, normalizeParsed, type DocumentView } from "../lib/parsed.ts";
import {
  DERIVED_BUCKET,
  PARSE_CACHE_PREFIX,
  getObjectText,
  putObjectJson,
} from "../lib/s3.ts";

const MAX_CHARS = 24_000;

function cacheKey(key: string): string {
  const sha = createHash("sha256").update(key).digest("hex").slice(0, 24);
  return `${PARSE_CACHE_PREFIX}${sha}.json`;
}

async function readCache(key: string): Promise<DocumentView | undefined> {
  try {
    const text = await getObjectText(DERIVED_BUCKET, cacheKey(key));
    return text ? normalizeParsed(JSON.parse(text)) : undefined;
  } catch {
    return undefined;
  }
}

function slicePages(view: DocumentView, start?: number, end?: number) {
  const from = start ?? 1;
  const to = end ?? (view.pageCount || from);
  const pages = view.pages.filter((p) => p.page >= from && p.page <= to);
  let used = 0;
  const out = [];
  let truncated = false;
  for (const p of pages) {
    if (used + p.markdown.length > MAX_CHARS) {
      truncated = true;
      // A single page larger than the budget still returns its head —
      // a page range cannot subdivide one page.
      if (out.length === 0) {
        out.push({ page: p.page, markdown: p.markdown.slice(0, MAX_CHARS) });
      }
      break;
    }
    used += p.markdown.length;
    out.push(p);
  }
  return { pages: out, truncated };
}

export default defineTool({
  description:
    "Read a corpus document's parsed content as page-addressed structured Markdown (or structured extraction fields with page citations for pilot tier-A documents). Parses on demand and caches when no parse exists yet. Always cite answers as (document key, page N) using the page numbers this tool returns. For long documents, request a page range.",
  inputSchema: z.object({
    key: z.string().min(1).describe("Exact S3 key from search_documents"),
    page_start: z.number().int().min(1).optional(),
    page_end: z.number().int().min(1).optional(),
  }),
  async execute({ key, page_start, page_end }) {
    const row = findByKey(key);
    if (!row) {
      return { error: "Key is not in the sample manifest. Use search_documents first." };
    }

    let view: DocumentView | undefined;
    let source = row.parse_source;

    if (row.parsed_ref) {
      view = await fetchParsedRef(row.parsed_ref);
    }
    if (!view) {
      view = await readCache(key);
      if (view) source = "doc-intel-cache";
    }
    if (!view) {
      if (row.parse_source === "pilot-failed" || row.parse_source === "pilot-skipped") {
        return {
          error: `This document failed parsing in the pilot (${row.parse_source}). It is likely a log-image TIF or vendor binary format that structured parsing cannot read. Report it as unreadable rather than guessing at its contents.`,
          entry_type: row.entry_type,
        };
      }
      const parsed = await parseWithLiteParse(key);
      if ("error" in parsed) return parsed;
      view = parsed.view;
      source = "liteparse-fresh";
      await putObjectJson(DERIVED_BUCKET, cacheKey(key), view);
    }

    if (view.kind === "extraction") {
      return {
        key,
        entry_type: row.entry_type,
        parse_source: source,
        kind: "extraction",
        fields: view.extraction?.fields ?? {},
        field_page_citations: view.extraction?.fieldPages ?? {},
      };
    }

    const { pages, truncated } = slicePages(view, page_start, page_end);
    return {
      key,
      entry_type: row.entry_type,
      parse_source: source,
      kind: "markdown",
      page_count: view.pageCount,
      pages,
      ...(truncated && {
        note: "Output truncated to stay within limits. Request a narrower page range for the rest.",
      }),
    };
  },
});
