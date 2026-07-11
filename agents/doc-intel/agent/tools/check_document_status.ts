import { defineTool } from "eve/tools";
import { z } from "zod";

const ANALYSTS_URL =
  process.env.DOC_INTEL_ANALYSTS_URL ?? "http://127.0.0.1:8734";

const matchSchema = z.object({
  doc_id: z.string(),
  s3key: z.string(),
  status: z.string(),
  reason: z.string(),
  page_count: z.number(),
  updated_at: z.string(),
  will_retry: z.boolean(),
});

const responseSchema = z.object({
  matches: z.array(matchSchema),
  summary: z.object({
    complete: z.number(),
    skipped: z.number(),
    failed: z.number(),
  }),
  total_matches: z.number(),
  ledger_as_of: z.string().nullable(),
});

export default defineTool({
  description:
    "Look up documents in the ingest ledger — the coverage source of truth for what the evidence store did with every WellDrive file it saw. Three-way answer per document: 'complete' (indexed, searchable), 'skipped' with a reason (deliberately declined — deferred format like spreadsheets/XML/email/ZIP, or an unreadable/oversize image; terminal for those exact bytes unless will_retry is true), or 'failed' (errored, retried every pass). Use this BEFORE claiming a document doesn't exist: a file can be in WellDrive but deliberately not indexed. Enumeration scope matters: the ledger saw the FULL Westlake Resources tranche but only the corpus sample for other asset teams — an empty result outside Westlake says almost nothing about the full archive, and an empty result anywhere may just mean the fragment guessed wrong (retry variations). Date absence claims with ledger_as_of — it marks when the ledger last changed (a proxy for the last ingest pass; a pass may be in progress or interrupted, and files added to WellDrive since the last pass are invisible to the ledger). During an active ingest pass, a document being re-ingested may briefly show no row — treat a surprising empty result as retriable, not settled.",
  inputSchema: z.object({
    name_query: z
      .string()
      .optional()
      .describe("Case-insensitive CONTIGUOUS filename/path fragment — one token works best (e.g. 'S617HF' or '.xlsx'); multi-word queries like 'S617HF frac summary' match nothing unless that exact string appears in the path"),
    asset_team: z
      .string()
      .optional()
      .describe("Restrict to one asset team's path prefix, e.g. WESTLAKE RESOURCES"),
    status: z
      .enum(["complete", "skipped", "failed"])
      .optional()
      .describe("Restrict to one ledger status"),
    limit: z.number().int().min(1).max(100).optional(),
  }),
  async execute({ name_query, asset_team, status, limit }) {
    let res: Response;
    try {
      res = await fetch(`${ANALYSTS_URL}/evidence/status`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name_query: name_query ?? "",
          asset_team,
          status,
          limit,
        }),
        signal: AbortSignal.timeout(60_000),
      });
    } catch {
      return {
        error:
          "The evidence store service is not reachable. State that ledger status could not be checked — do not make absence claims without it.",
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
