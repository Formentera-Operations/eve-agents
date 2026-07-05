import { readFileSync } from "node:fs";
import { resolve } from "node:path";

export interface ManifestRow {
  key: string;
  asset_team: string;
  well: string;
  category: string;
  entry_type: string;
  well_name_meta: string;
  bytes: string;
  parse_source: string;
  parsed_ref: string;
}

const MANIFEST_PATH =
  process.env.WELLDRIVE_MANIFEST ??
  resolve(process.cwd(), "../../corpus/sample-manifest.csv");

let cached: ManifestRow[] | undefined;

// Minimal RFC-4180 parser: handles quoted fields with embedded commas, which
// WellDrive keys contain (e.g. `GOODNIGHT,_SELMA_2H`).
function parseCsvLine(line: string): string[] {
  const fields: string[] = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"' && line[i + 1] === '"') {
        field += '"';
        i++;
      } else if (ch === '"') {
        inQuotes = false;
      } else {
        field += ch;
      }
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      fields.push(field);
      field = "";
    } else {
      field += ch;
    }
  }
  fields.push(field);
  return fields;
}

export function loadManifest(): ManifestRow[] {
  if (cached) return cached;
  const text = readFileSync(MANIFEST_PATH, "utf8");
  // The manifest is written by Python's csv module, which emits CRLF.
  const lines = text.split(/\r?\n/).filter((l) => l.length > 0);
  const header = parseCsvLine(lines[0]);
  cached = lines.slice(1).map((line) => {
    const values = parseCsvLine(line);
    const row = Object.fromEntries(header.map((h, i) => [h, values[i] ?? ""]));
    return row as unknown as ManifestRow;
  });
  return cached;
}

export function findByKey(key: string): ManifestRow | undefined {
  return loadManifest().find((r) => r.key === key);
}
