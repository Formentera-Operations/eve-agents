import { defineTool } from "eve/tools";
import { z } from "zod";

import { ANALYSTS_URL, analystError, analystHeaders } from "../lib/analysts.ts";

const matchSchema = z.object({
  page_id: z.string(),
  doc_id: z.string(),
  page_num: z.number(),
  s3key: z.string(),
  asset_team: z.string(),
  match: z.string(),
  context: z.string(),
});

const responseSchema = z.object({
  matches: z.array(matchSchema),
});

export default defineTool({
  description:
    "Exact substring or regex search over evidence page text (the 500-file sample plus all indexed Westlake Resources documents) — a true scan, so alphanumeric codes semantic search mangles (well codes like S733H, API numbers, lease IDs) are found exactly. Returns each match with surrounding context and its page identity. Use this whenever the question contains an exact identifier; use search_evidence for meaning-shaped queries.",
  inputSchema: z.object({
    pattern: z.string().min(1).describe("Exact substring, or a regex if regex=true"),
    regex: z.boolean().optional().describe("Treat pattern as a regular expression"),
    limit: z.number().int().min(1).max(100).optional(),
    asset_team: z
      .string()
      .optional()
      .describe("Restrict to one asset team, e.g. WESTLAKE RESOURCES"),
  }),
  async execute({ pattern, regex, limit, asset_team }) {
    let res: Response;
    try {
      res = await fetch(`${ANALYSTS_URL}/evidence/grep`, {
        method: "POST",
        headers: analystHeaders(),
        body: JSON.stringify({ pattern, regex, limit, asset_team }),
        signal: AbortSignal.timeout(120_000),
      });
    } catch {
      return {
        error:
          "The evidence store service is not reachable. Fall back to search_documents and read_parsed_document, and state that evidence grep was unavailable.",
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
        "Matches are page-level. Read the page with read_evidence before citing it; cite as (s3key, page_num).",
    };
  },
});
