import { defineTool } from "eve/tools";
import { z } from "zod";

import { loadManifest } from "../lib/manifest.ts";

export default defineTool({
  description:
    "Search the 500-file WellDrive corpus manifest. Filter by asset team, well name, entry_type (the authoritative document classification from S3 metadata), parse status, or a substring of the S3 key. Returns matching rows with their parse status. Start broad, then narrow.",
  inputSchema: z.object({
    asset_team: z.string().optional().describe("Exact asset team, e.g. 'FP GRIFFIN'"),
    well: z.string().optional().describe("Case-insensitive substring of the well directory name"),
    entry_type: z.string().optional().describe("Exact entry_type, e.g. 'AFE', 'Well Test', 'Frac Report'"),
    key_contains: z.string().optional().describe("Case-insensitive substring of the S3 key"),
    parse_source: z.string().optional().describe("Filter by parse status: pilot-tierA, pilot-tierB, pilot-tierC, pilot-failed, pilot-skipped, unparsed"),
    limit: z.number().int().min(1).max(100).default(25),
  }),
  execute({ asset_team, well, entry_type, key_contains, parse_source, limit }) {
    const rows = loadManifest().filter((r) => {
      if (asset_team && r.asset_team !== asset_team) return false;
      if (well && !r.well.toLowerCase().includes(well.toLowerCase())) return false;
      if (entry_type && r.entry_type !== entry_type) return false;
      if (key_contains && !r.key.toLowerCase().includes(key_contains.toLowerCase())) return false;
      if (parse_source && r.parse_source !== parse_source) return false;
      return true;
    });
    return {
      total_matches: rows.length,
      returned: Math.min(rows.length, limit),
      documents: rows.slice(0, limit).map((r) => ({
        key: r.key,
        asset_team: r.asset_team,
        well: r.well,
        entry_type: r.entry_type,
        category: r.category,
        parse_source: r.parse_source,
      })),
    };
  },
});
