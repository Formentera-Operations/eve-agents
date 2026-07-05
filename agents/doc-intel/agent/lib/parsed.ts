import { DERIVED_BUCKET, getObjectText, parseS3Uri } from "./s3.ts";

export interface DocumentPage {
  page: number;
  markdown: string;
}

export interface DocumentView {
  kind: "markdown" | "extraction";
  pages: DocumentPage[];
  /** Structured fields with per-field page citations (pilot tier A). */
  extraction?: {
    fields: Record<string, unknown>;
    fieldPages: Record<string, number[]>;
  };
  pageCount: number;
}

interface ParseChunk {
  type?: string;
  content?: string;
  metadata?: { pageRange?: { start?: number; end?: number } };
}

/**
 * Normalize a cached parse JSON (pilot tier A extraction runs, tier B/C
 * parse runs, or doc-intel LiteParse cache entries) into one view.
 */
export function normalizeParsed(raw: unknown): DocumentView {
  const doc = raw as Record<string, unknown>;

  // doc-intel cache entries are already in DocumentView shape.
  if (Array.isArray(doc.pages) && (doc.kind === "markdown" || doc.kind === "extraction")) {
    return doc as unknown as DocumentView;
  }

  const output = doc.output as Record<string, unknown> | undefined;

  // Parse run: page-chunked markdown.
  if (output && Array.isArray(output.chunks)) {
    const pages: DocumentPage[] = (output.chunks as ParseChunk[])
      .filter((c) => typeof c.content === "string")
      .map((c, i) => ({
        page: c.metadata?.pageRange?.start ?? i + 1,
        markdown: c.content ?? "",
      }));
    return { kind: "markdown", pages, pageCount: pages.length };
  }

  // Extract run: structured fields + per-field page citations.
  if (output && output.value && typeof output.value === "object") {
    const fields = output.value as Record<string, unknown>;
    const fieldPages: Record<string, number[]> = {};
    const meta = (output.metadata ?? {}) as Record<
      string,
      { citations?: { page?: { number?: number } }[] }
    >;
    for (const [name, m] of Object.entries(meta)) {
      const pages = (m?.citations ?? [])
        .map((c) => c.page?.number)
        .filter((n): n is number => typeof n === "number");
      if (pages.length > 0) fieldPages[name] = pages;
    }
    const cited = Object.values(fieldPages).flat();
    return {
      kind: "extraction",
      pages: [],
      extraction: { fields, fieldPages },
      pageCount: cited.length > 0 ? Math.max(...cited) : 0,
    };
  }

  return { kind: "markdown", pages: [], pageCount: 0 };
}

export async function fetchParsedRef(parsedRef: string): Promise<DocumentView | undefined> {
  const loc = parseS3Uri(parsedRef);
  if (!loc) return undefined;
  const text = await getObjectText(loc.bucket ?? DERIVED_BUCKET, loc.key);
  if (!text) return undefined;
  return normalizeParsed(JSON.parse(text));
}
