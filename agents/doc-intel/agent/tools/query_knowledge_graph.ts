import { defineTool } from "eve/tools";
import { z } from "zod";

const ANALYSTS_URL =
  process.env.DOC_INTEL_ANALYSTS_URL ?? "http://127.0.0.1:8734";

const responseSchema = z.object({
  answer: z.string(),
  sources: z.array(z.string()),
  evidence_doc_ids: z.array(z.string()).default([]),
  mode: z.string(),
});

export default defineTool({
  description:
    "Query the corpus knowledge graph for entity-shaped questions: everything about a well, connections between wells/vendors/operators/formations, events across documents. Returns a graph-grounded answer plus the source document keys it drew from. Graph citations are document-level — verify page-level content before presenting: sample-manifest keys via read_parsed_document; evidence-store documents via read_evidence using the returned evidence_doc_ids (their keys are NOT in the sample manifest). Say the answer came from the knowledge graph. If this tool errors or the graph lacks the answer, fall back to the evidence and manifest tools and say so.",
  inputSchema: z.object({
    question: z.string().min(1).describe("The entity-shaped question"),
    entity_scope: z
      .array(z.string())
      .optional()
      .describe("Optional corpus S3 keys to scope the search to"),
  }),
  async execute({ question, entity_scope }) {
    let res: Response;
    try {
      res = await fetch(`${ANALYSTS_URL}/graph/search`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question, entity_scope }),
        signal: AbortSignal.timeout(120_000),
      });
    } catch {
      return {
        error:
          "The knowledge graph service is not reachable. Answer from search_documents and read_parsed_document instead, and state that graph memory was unavailable.",
      };
    }
    if (!res.ok) {
      return { error: `Knowledge graph service responded ${res.status}.` };
    }
    const parsed = responseSchema.safeParse(await res.json());
    if (!parsed.success) {
      return { error: "Knowledge graph service returned an unexpected shape." };
    }
    return {
      ...parsed.data,
      reminder:
        "Sources are document-level. Verify page-level citations before presenting — read_parsed_document for sample-manifest keys, read_evidence with the evidence_doc_ids for evidence-store documents; drop any fact you cannot pin to a page.",
    };
  },
});
