import { defineTool } from "eve/tools";
import { z } from "zod";

import { ANALYSTS_URL, analystError, analystHeaders } from "../lib/analysts.ts";

const hitSchema = z.object({
  page_id: z.string(),
  doc_id: z.string(),
  page_num: z.number(),
  s3key: z.string(),
  asset_team: z.string(),
  score: z.number(),
  signals: z.record(z.string(), z.number()),
  snippet: z.string(),
});

const responseSchema = z.object({
  hits: z.array(hitSchema),
  mode: z.string(),
});

export default defineTool({
  description:
    "Semantic search over the evidence store: page text, page images, and extracted figures across the 500-file corpus sample plus the Westlake Resources tranche (~32,600 indexed Westlake documents — every parseable Westlake well file in the archive; deferred formats like spreadsheets and email are gate-skipped and not searchable), merged to page-ranked results. The default hybrid_bundle mode combines text and visual signals; direct modes narrow to one (chunks, pages, fts, images, assets). Every hit carries its page_id and corpus S3 key — cite pages from these, and use read_evidence on a page_id to read the page before citing it. For exact strings (well codes, API numbers) use grep_evidence instead.",
  inputSchema: z.object({
    query: z.string().min(1).describe("Plain-language content question"),
    mode: z
      .enum(["hybrid_bundle", "chunks", "pages", "fts", "images", "assets"])
      .optional()
      .describe("Search mode; hybrid_bundle (default) merges all signals"),
    limit: z.number().int().min(1).max(25).optional(),
    asset_team: z
      .string()
      .optional()
      .describe("Restrict to one asset team, e.g. WESTLAKE RESOURCES"),
  }),
  async execute({ query, mode, limit, asset_team }) {
    let res: Response;
    try {
      res = await fetch(`${ANALYSTS_URL}/evidence/search`, {
        method: "POST",
        headers: analystHeaders(),
        body: JSON.stringify({ query, mode, limit, asset_team }),
        signal: AbortSignal.timeout(60_000),
      });
    } catch {
      return {
        error:
          "The evidence store service is not reachable. Fall back to search_documents and read_parsed_document, and state that evidence search was unavailable.",
      };
    }
    if (!res.ok) {
      return { error: analystError("Evidence service", res.status) };
    }
    const parsed = responseSchema.safeParse(await res.json());
    if (!parsed.success) {
      return { error: "Evidence service returned an unexpected shape." };
    }
    return {
      ...parsed.data,
      reminder:
        "Hits are page-level. Read the page with read_evidence before citing it; cite as (s3key, page_num).",
    };
  },
});
