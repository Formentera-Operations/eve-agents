import { defineTool } from "eve/tools";
import { z } from "zod";

import { findByKey } from "../lib/manifest.ts";

const ANALYSTS_URL =
  process.env.DOC_INTEL_ANALYSTS_URL ?? "http://127.0.0.1:8734";

const responseSchema = z.object({
  answer: z.string(),
  citations: z.array(z.object({ key: z.string(), page: z.number() })),
  analyst_notes: z.string().default(""),
  documents_seeded: z.number().default(0),
  documents_missing: z.array(z.string()).default([]),
});

export default defineTool({
  description:
    "Delegate a multi-document analysis question to the specialist analyst service (per-document-class analysts: drilling ops, completions, wellbore geometry, fluids, reservoir, financial, logs). Pass the corpus keys of the documents to analyze — they must already be parseable (use read_parsed_document first to confirm at least one page loads). Returns an answer with (key, page) citations, which you MUST verify with read_parsed_document before presenting.",
  inputSchema: z.object({
    question: z.string().min(1).describe("The precise analysis question"),
    document_keys: z
      .array(z.string().min(1))
      .min(1)
      .max(25)
      .describe("Corpus S3 keys of the documents to analyze together"),
  }),
  async execute({ question, document_keys }) {
    const documents = [];
    const unknown: string[] = [];
    for (const key of document_keys) {
      const row = findByKey(key);
      if (!row) {
        unknown.push(key);
        continue;
      }
      documents.push({
        key: row.key,
        entry_type: row.entry_type,
        parsed_ref: row.parsed_ref,
      });
    }
    if (documents.length === 0) {
      return { error: "None of the given keys are in the sample manifest.", unknown_keys: unknown };
    }

    let res: Response;
    try {
      res = await fetch(`${ANALYSTS_URL}/analyze`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question, documents }),
        signal: AbortSignal.timeout(600_000),
      });
    } catch {
      return {
        error:
          "The analyst service is not reachable. Answer from your own document reads instead, and note that specialist analysis was unavailable.",
      };
    }
    if (!res.ok) {
      return { error: `Analyst service responded ${res.status}.` };
    }

    const parsed = responseSchema.safeParse(await res.json());
    if (!parsed.success) {
      return { error: "Analyst service returned an unexpected shape." };
    }
    return {
      ...parsed.data,
      ...(unknown.length > 0 && { unknown_keys_skipped: unknown }),
      reminder:
        "Verify each citation with read_parsed_document before repeating it to the user.",
    };
  },
});
