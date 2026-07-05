import { defineTool } from "eve/tools";
import { z } from "zod";

import { findByKey } from "../lib/manifest.ts";
import { CORPUS_BUCKET, headMetadata } from "../lib/s3.ts";

export default defineTool({
  description:
    "Get full detail for one corpus document by its S3 key: manifest row plus live S3 object metadata (entry_type, well_name, welldrive_file_id, size, content type). Use the exact key returned by search_documents.",
  inputSchema: z.object({
    key: z.string().min(1).describe("Exact S3 key within the corpus bucket"),
  }),
  async execute({ key }) {
    const row = findByKey(key);
    if (!row) {
      return { error: "Key is not in the 500-file sample manifest. Use search_documents to find valid keys." };
    }
    try {
      const head = await headMetadata(CORPUS_BUCKET, key);
      return { manifest: row, s3: head };
    } catch {
      return { manifest: row, s3: { error: "S3 head request failed" } };
    }
  },
});
