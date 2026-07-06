"""Generate named individuals for welldrive.owl (ontology-individuals plan U1-U3).

Deterministic generator: extracts per-class candidate names from the graph
exports and corpus manifest (U1), verifies them against snowsql-exported
Snowflake masters (U2), and rewrites the marked individuals block of
references/ontology/welldrive.owl (U3). Offline tooling like graph.export —
never imported by the service runtime.

Usage: uv run python -m doc_intel_analysts.graph.individuals --help
"""

import csv
from pathlib import Path
from typing import Iterable, TextIO

# cognee's RDFLibOntologyResolver derives match keys from URI local names via
# _uri_to_key: lower, spaces->underscores, strip. Runtime extracted names get
# the identical treatment in find_closest_match. This function must stay
# byte-identical to that normalization — no extra whitespace collapse — so
# minted fragments hit the exact-match path (KTD2).
def normalize_key(name: str) -> str:
    return name.lower().replace(" ", "_").strip()


# Extracted-entity EntityType names (lowercased in the graph) that feed each
# candidate pool. Organizations feed both Operator and ServiceVendor pools;
# U2 verification against the class-specific master decides which survives.
ENTITY_TYPE_POOLS: dict[str, frozenset[str]] = {
    "Well": frozenset({"well", "oilwell", "wellbore", "oil well", "gas well"}),
    "Operator": frozenset({"organization", "company", "operator"}),
    "ServiceVendor": frozenset(
        {"organization", "company", "servicecompany", "service company", "vendor", "contractor"}
    ),
    "County": frozenset({"location", "county", "geographicarea", "geographic area"}),
}

CLASSES = ("Well", "Operator", "ServiceVendor", "County", "AssetTeam")


def read_csv_rows(source: Path | TextIO) -> Iterable[dict[str, str]]:
    """DictReader over a path or open file. The corpus manifest is CRLF
    (written by Python csv); csv.DictReader handles both endings natively."""
    if isinstance(source, Path):
        with source.open(newline="", encoding="utf-8") as handle:
            yield from csv.DictReader(handle)
    else:
        yield from csv.DictReader(source)


def _add(pool: dict[str, str], name: str) -> None:
    """Dedupe by normalized key, keeping the first-seen original spelling."""
    spelling = name.strip()
    if not spelling:
        return
    key = normalize_key(spelling)
    if key and key not in pool:
        pool[key] = spelling


def extract_candidates(
    nodes: Path | TextIO,
    edges: Path | TextIO,
    manifest: Path | TextIO,
) -> dict[str, dict[str, str]]:
    """Per-class candidate pools: {class: {normalized_key: original_spelling}}.

    Graph-export side: Entity nodes reach their extractor-assigned type via
    is_a edges to EntityType nodes (1,766 such edges in the current export).
    Manifest side: the asset_team and well columns are authoritative
    document-side spellings (directory names in the corpus paths).
    """
    pools: dict[str, dict[str, str]] = {cls: {} for cls in CLASSES}

    entity_names: dict[str, str] = {}
    entity_type_names: dict[str, str] = {}
    for row in read_csv_rows(nodes):
        if row["type"] == "Entity":
            entity_names[row["id"]] = row["name"]
        elif row["type"] == "EntityType":
            entity_type_names[row["id"]] = row["name"].strip().lower()

    for row in read_csv_rows(edges):
        if row["label"] != "is_a":
            continue
        name = entity_names.get(row["source"])
        entity_type = entity_type_names.get(row["target"])
        if name is None or entity_type is None:
            continue
        for cls, type_names in ENTITY_TYPE_POOLS.items():
            if entity_type in type_names:
                _add(pools[cls], name)

    for row in read_csv_rows(manifest):
        _add(pools["AssetTeam"], row["asset_team"])
        _add(pools["Well"], row["well"])

    return pools


def _main() -> None:  # pragma: no cover — CLI wiring lands with U3
    raise SystemExit("CLI arrives with U3; import extract_candidates for now")


if __name__ == "__main__":
    _main()
