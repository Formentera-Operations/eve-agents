import { defineTool } from "eve/tools";
import { z } from "zod";

const ANALYSTS_URL =
  process.env.DOC_INTEL_ANALYSTS_URL ?? "http://127.0.0.1:8734";

const documentSchema = z.object({
  doc_id: z.string(),
  s3key: z.string(),
  asset_team: z.string(),
  format_gate: z.string(),
  page_count: z.number(),
});

const responseSchema = z.object({
  documents: z.array(documentSchema),
});

export default defineTool({
  description:
    "Find documents in the evidence store by filename fragment, asset team, or format (pdf, text, image). Complements search_documents: the evidence store also covers Westlake Resources files that the sample manifest lacks. Returns doc_ids usable with read_evidence and search filters.",
  inputSchema: z.object({
    name_query: z
      .string()
      .optional()
      .describe("Case-insensitive CONTIGUOUS filename/path fragment — one token works best (e.g. 'S617HF' or 'CBL'); multi-word queries like 'S617HF schematic' match nothing unless that exact string appears in the path"),
    asset_team: z
      .string()
      .optional()
      .describe("Restrict to one asset team, e.g. WESTLAKE RESOURCES"),
    format_gate: z
      .enum(["pdf", "text", "image"])
      .optional()
      .describe("Restrict to one ingest format gate"),
    limit: z.number().int().min(1).max(100).optional(),
  }),
  async execute({ name_query, asset_team, format_gate, limit }) {
    let res: Response;
    try {
      res = await fetch(`${ANALYSTS_URL}/evidence/find`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name_query: name_query ?? "",
          asset_team,
          format_gate,
          limit,
        }),
        signal: AbortSignal.timeout(60_000),
      });
    } catch {
      return {
        error:
          "The evidence store service is not reachable. Fall back to search_documents, and state that the evidence file index was unavailable.",
      };
    }
    if (!res.ok) {
      return { error: `Evidence service responded ${res.status}.` };
    }
    const parsed = responseSchema.safeParse(await res.json());
    if (!parsed.success) {
      return { error: "Evidence service returned an unexpected shape." };
    }
    return parsed.data;
  },
});
