import { defineTool } from "eve/tools";
import { z } from "zod";

import { loadManifest } from "../lib/manifest.ts";

export default defineTool({
  description:
    "Get an aggregate overview of the corpus: document counts by asset team and by entry_type, and how many are already parsed vs unparsed. Call this first to orient before searching.",
  inputSchema: z.object({}),
  execute() {
    const rows = loadManifest();
    const count = (pick: (r: (typeof rows)[number]) => string) => {
      const acc: Record<string, number> = {};
      for (const r of rows) {
        const k = pick(r) || "(none)";
        acc[k] = (acc[k] ?? 0) + 1;
      }
      return Object.fromEntries(Object.entries(acc).sort((a, b) => b[1] - a[1]));
    };
    return {
      total_documents: rows.length,
      by_asset_team: count((r) => r.asset_team),
      by_entry_type: count((r) => r.entry_type),
      by_parse_source: count((r) => r.parse_source),
    };
  },
});
