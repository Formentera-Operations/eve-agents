"""Generate named individuals for welldrive.owl (ontology-individuals plan U1-U3).

Deterministic generator: extracts per-class candidate names from the graph
exports and corpus manifest (U1), verifies them against snowsql-exported
Snowflake masters (U2), and rewrites the marked individuals block of
references/ontology/welldrive.owl (U3). Offline tooling like graph.export —
never imported by the service runtime.

Usage: uv run python -m doc_intel_analysts.graph.individuals --help
"""

import csv
import difflib
from dataclasses import dataclass
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

# Verification claims keys in this order — AssetTeam first (closed
# authoritative set from the manifest), Operator ahead of ServiceVendor.
CLASSES = ("AssetTeam", "Well", "Operator", "ServiceVendor", "County")


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

    # Typing via is_a edges is sparse (~1,700 of ~4,700 entities carry one),
    # so real well/org mentions hide among untyped entities. Sweep every
    # extracted entity name into a catch-all pool; verification against the
    # masters is the precision filter (KTD7 knob: widen candidate sources).
    sweep: dict[str, str] = {}
    for name in entity_names.values():
        _add(sweep, name)
    pools["_sweep"] = sweep

    return pools


# --- U2: verification against snowsql-exported masters -----------------------

# Generator-side matching is stricter than cognee's 0.8 runtime cutoff (KTD6):
# precision is controlled by what enters the OWL.
VERIFY_CUTOFF = 0.9


@dataclass(frozen=True)
class Verified:
    """A candidate confirmed against a master. master_key is report-only
    working data — it never enters the committed OWL (plan KTD4/U3)."""

    name: str
    cls: str
    master_source: str
    master_key: str
    score: float


def load_master_csv(path: Path, filename_hint: str) -> list[dict[str, str]]:
    """Fail loud when the snow-CLI export step was skipped (mirrors the
    ontology-path guard convention)."""
    if not path.exists():
        raise FileNotFoundError(
            f"master export missing: {path} — run the snow sql export in "
            f"references/ontology/masters/{filename_hint} first"
        )
    return list(read_csv_rows(path))


def _master_lookup(rows: Iterable[dict[str, str]], name_cols: tuple[str, ...], key_col: str, source: str) -> dict[str, tuple[str, str]]:
    """normalized master name -> (source, key). First-seen wins for stability."""
    lookup: dict[str, tuple[str, str]] = {}
    for row in rows:
        key = (row.get(key_col) or "").strip()
        for col in name_cols:
            name = (row.get(col) or "").strip()
            norm = normalize_key(name)
            if norm and norm not in lookup:
                lookup[norm] = (source, key or name)
    return lookup


def _match(candidate_key: str, lookup: dict[str, tuple[str, str]]) -> tuple[str, str, float] | None:
    if candidate_key in lookup:
        source, key = lookup[candidate_key]
        return source, key, 1.0
    close = difflib.get_close_matches(candidate_key, list(lookup), n=1, cutoff=VERIFY_CUTOFF)
    if not close:
        return None
    source, key = lookup[close[0]]
    score = difflib.SequenceMatcher(None, candidate_key, close[0]).ratio()
    return source, key, round(score, 3)


def _match_org_prefix(candidate_key: str, lookup: dict[str, tuple[str, str]]) -> tuple[str, str, float] | None:
    """Org names in documents drop legal suffixes the masters keep
    ('premier corex' vs 'PREMIER COREX LLC'). Verify when the candidate is a
    whole-token prefix of a master name. Guarded to substantial candidates
    (>=8 chars or >=2 tokens) so short fragments can't false-match."""
    if len(candidate_key) < 8 and "_" not in candidate_key:
        return None
    matches = [
        key for key in lookup
        if key.startswith(candidate_key)
        and (len(key) == len(candidate_key) or key[len(candidate_key)] == "_")
    ]
    if not matches:
        return None
    best = min(matches, key=lambda k: (len(k), k))
    source, master_key = lookup[best]
    score = difflib.SequenceMatcher(None, candidate_key, best).ratio()
    return source, master_key, round(score, 3)


def _strip_county_suffix(key: str) -> str:
    for suffix in ("_county", "_county,_tx", "_county,_nd"):
        if key.endswith(suffix):
            return key[: -len(suffix)]
    return key


_WELL_NUMBER = __import__("re").compile(r"_#?\d+[a-z]{0,3}(_st\d+|_rd)?$")


def _strip_well_number(key: str) -> str:
    """'boles,_verdia_1h' -> 'boles,_verdia' — the corpus names wells as
    lease + well number, while master WELL_NAME often uses another
    convention; the lease name is the stable stem to verify against."""
    return _WELL_NUMBER.sub("", key)


def verify_candidates(
    pools: dict[str, dict[str, str]],
    well_master: list[dict[str, str]],
    vendor_master: list[dict[str, str]],
) -> tuple[list[Verified], list[dict[str, str]]]:
    """Split candidates into verified individuals and an unverified report (R4).

    Per-class masters (KTD4): Well -> WELL_NAME/LEASE_NAME; Operator ->
    COMPANY_NAME/OPERATOR_NAME; ServiceVendor -> VENDOR_NAME/VENDOR_FULL_NAME;
    County -> COUNTY of wells the corpus matched (suffix-tolerant); AssetTeam
    -> the manifest itself is authoritative (a closed set of directory names).
    """
    lookups = {
        "Well": _master_lookup(well_master, ("WELL_NAME", "LEASE_NAME"), "EID", "gold_dim_well"),
        "WellLease": _master_lookup(well_master, ("LEASE_NAME",), "LEASE_NAME", "gold_dim_well (lease)"),
        "Operator": _master_lookup(well_master, ("COMPANY_NAME", "OPERATOR_NAME"), "COMPANY_NAME", "gold_dim_well"),
        "ServiceVendor": _master_lookup(vendor_master, ("VENDOR_NAME", "VENDOR_FULL_NAME"), "VENDOR_ID", "gold_dim_vendor"),
        "County": _master_lookup(well_master, ("COUNTY",), "COUNTY", "gold_dim_well"),
    }

    def check(cls: str, key: str) -> tuple[str, str, float] | None:
        probe = _strip_county_suffix(key) if cls == "County" else key
        hit = _match(probe, lookups[cls])
        if hit is None and cls == "Well":
            stem = _strip_well_number(probe)
            if stem != probe:
                hit = _match(stem, lookups["WellLease"])
        if hit is None and cls in ("Operator", "ServiceVendor"):
            hit = _match_org_prefix(probe, lookups[cls])
        return hit

    verified: dict[str, Verified] = {}
    unverified: list[dict[str, str]] = []
    for cls in CLASSES:
        for key, spelling in sorted(pools.get(cls, {}).items()):
            if key in verified:
                continue  # first class wins (CLASSES order: Operator over ServiceVendor)
            if cls == "AssetTeam":
                verified[key] = Verified(spelling, cls, "manifest", spelling, 1.0)
                continue
            hit = check(cls, key)
            if hit is None:
                nearest = difflib.get_close_matches(key, list(lookups[cls]), n=1, cutoff=0.0)
                unverified.append({
                    "name": spelling, "class": cls,
                    "nearest_master": nearest[0] if nearest else "",
                    "score": str(round(difflib.SequenceMatcher(None, key, nearest[0]).ratio(), 3)) if nearest else "",
                })
                continue
            source, master_key, score = hit
            verified[key] = Verified(spelling, cls, source, master_key, score)

    # Catch-all sweep: names outside the typed pools verify silently or drop —
    # they never enter the unverified report (that would drown real misses).
    for key, spelling in sorted(pools.get("_sweep", {}).items()):
        if key in verified:
            continue
        for cls in ("Well", "Operator", "ServiceVendor", "County"):
            hit = check(cls, key)
            if hit is not None:
                source, master_key, score = hit
                verified[key] = Verified(spelling, cls, source, master_key, score)
                break

    return list(verified.values()), unverified


def _main() -> None:  # pragma: no cover — CLI wiring lands with U3
    raise SystemExit("CLI arrives with U3; import extract_candidates for now")


if __name__ == "__main__":
    _main()
