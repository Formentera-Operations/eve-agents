import type { DocumentView } from "./parsed.ts";

/**
 * Parse a corpus document with LiteParse and return a DocumentView.
 * Placeholder pending integration wiring; read_parsed_document already
 * handles the cached and pilot-parsed paths without this.
 */
export async function parseWithLiteParse(
  key: string,
): Promise<{ view: DocumentView } | { error: string }> {
  if (!process.env.LITEPARSE_API_KEY) {
    return {
      error:
        "LITEPARSE_API_KEY is not configured, and this document has no cached parse. Report the document as not yet parseable in this environment.",
    };
  }
  return { error: `LiteParse integration pending for ${key}.` };
}
