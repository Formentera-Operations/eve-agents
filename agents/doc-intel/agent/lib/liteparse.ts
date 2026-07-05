import { LiteParse } from "@llamaindex/liteparse";

import type { DocumentView } from "./parsed.ts";
import { CORPUS_BUCKET, getObjectBytes } from "./s3.ts";

// Module-level parsers, reused across calls (the intended LiteParse pattern).
// OCR is opt-in per document via isComplex triage — born-digital PDFs parse
// much faster without it.
const plainParser = new LiteParse({ outputFormat: "markdown", ocrEnabled: false });
const ocrParser = new LiteParse({ outputFormat: "markdown", ocrEnabled: true });

// LiteParse parses PDFs natively; Office/OpenDocument need LibreOffice and
// images need ImageMagick on the host. Vendor log/binary formats are out.
const PARSEABLE = new Set([".pdf", ".docx", ".xlsx", ".pptx", ".doc", ".xls", ".png", ".jpg", ".jpeg", ".tif", ".tiff"]);

export function extensionOf(key: string): string {
  const name = key.split("/").pop() ?? "";
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

export async function parseBytesToView(bytes: Uint8Array): Promise<DocumentView> {
  let needsOcr = false;
  try {
    const stats = await plainParser.isComplex(bytes);
    needsOcr = stats.some((p) => p.needsOcr);
  } catch {
    // isComplex can fail on non-PDF inputs that parse() handles via
    // conversion; fall through with OCR off and let parse() decide.
  }
  const result = await (needsOcr ? ocrParser : plainParser).parse(bytes);
  const pages = result.pages.map((p) => ({ page: p.pageNum, markdown: p.markdown || p.text }));
  return { kind: "markdown", pages, pageCount: pages.length };
}

/**
 * Parse a corpus document with LiteParse (local, in-process, no credentials)
 * and return a page-addressed DocumentView.
 */
export async function parseWithLiteParse(
  key: string,
): Promise<{ view: DocumentView } | { error: string }> {
  const ext = extensionOf(key);
  if (!PARSEABLE.has(ext)) {
    return {
      error: `Format '${ext || "unknown"}' is not parseable here (vendor/log binary). Report the document as not machine-readable.`,
    };
  }
  let bytes: Uint8Array;
  try {
    bytes = await getObjectBytes(CORPUS_BUCKET, key);
  } catch {
    return { error: "Could not fetch the document bytes from S3." };
  }
  if (bytes.length === 0) {
    return { error: "The S3 object is empty." };
  }
  try {
    const view = await parseBytesToView(bytes);
    if (view.pageCount === 0) {
      return { error: "LiteParse produced no pages for this document." };
    }
    return { view };
  } catch (err) {
    const message = err instanceof Error ? err.message : "unknown parser error";
    return { error: `LiteParse failed: ${message}` };
  }
}
