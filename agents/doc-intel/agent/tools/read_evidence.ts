import { defineTool } from "eve/tools";
import { z } from "zod";

const ANALYSTS_URL =
  process.env.DOC_INTEL_ANALYSTS_URL ?? "http://127.0.0.1:8734";

const pageReadSchema = z.object({
  page_id: z.string(),
  doc_id: z.string(),
  page_num: z.number(),
  s3key: z.string(),
  asset_team: z.string(),
  text: z.string(),
  has_screenshot: z.boolean(),
  vision_finding: z.string().optional(),
  vision_citation: z
    .object({ s3key: z.string(), page: z.number() })
    .optional(),
});

const docReadSchema = z.object({
  doc_id: z.string(),
  s3key: z.string(),
  pages: z.array(
    z.object({ page_id: z.string(), page_num: z.number(), text: z.string() }),
  ),
});

export default defineTool({
  description:
    "Read a page (or whole document) from the evidence store by page_id or doc_id. Returns the page text. For visual evidence — log plots, charts, figures, stamped forms — pass a question: the analysts service reads the stored page screenshot through gateway vision and returns a text finding with its page citation. Always read a page before citing it; cite as (s3key, page_num).",
  inputSchema: z
    .object({
      page_id: z
        .string()
        .optional()
        .describe("Page identity from search/grep hits, e.g. doc-abc12345:p3"),
      doc_id: z
        .string()
        .optional()
        .describe("Read all pages of a document instead of one page"),
      question: z
        .string()
        .optional()
        .describe(
          "Ask about what is VISIBLE on the page image (requires page_id); use when text alone cannot answer",
        ),
    })
    .refine((v) => v.page_id || v.doc_id, {
      message: "page_id or doc_id is required",
    }),
  async execute({ page_id, doc_id, question }) {
    let res: Response;
    try {
      res = await fetch(`${ANALYSTS_URL}/evidence/read`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ page_id, doc_id, question }),
        signal: AbortSignal.timeout(120_000),
      });
    } catch {
      return {
        error:
          "The evidence store service is not reachable. Fall back to read_parsed_document, and state that evidence reading was unavailable.",
      };
    }
    if (res.status === 404) {
      return { error: "Unknown page_id or doc_id — take identities from search_evidence, grep_evidence, or find_evidence_files hits." };
    }
    if (!res.ok) {
      return { error: `Evidence service responded ${res.status}.` };
    }
    const body = await res.json();
    const parsed = pageReadSchema.safeParse(body);
    if (parsed.success) {
      return parsed.data;
    }
    const docParsed = docReadSchema.safeParse(body);
    if (docParsed.success) {
      return docParsed.data;
    }
    return { error: "Evidence service returned an unexpected shape." };
  },
});
