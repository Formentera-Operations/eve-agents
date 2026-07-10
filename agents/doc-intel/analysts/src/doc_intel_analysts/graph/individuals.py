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
import json
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


def _edge_relationship(row: dict[str, str]) -> str:
    """Exports written before the export.py label fix carry the storage-table
    name in `label`; the semantic relationship lives in properties. Prefer
    properties so cached pre-fix exports still yield candidates."""
    props = row.get("properties") or ""
    if '"relationship_name"' not in props:
        return row["label"]
    try:
        return str(json.loads(props).get("relationship_name") or row["label"])
    except json.JSONDecodeError:
        return row["label"]


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
        if _edge_relationship(row) != "is_a":
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


def load_aliases(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    """Hand-curated alias exceptions (references/ontology/aliases.csv):
    corporate renames and brands that bill through a parent — cases no string
    metric can bridge ('liberty oilfield services' renamed to Liberty Energy
    in 2022; Baroid is a Halliburton product service line). Keyed by
    (class, normalized alias) -> {spelling, master (normalized)}. Every row
    mints an individual even before any extracted candidate carries the
    spelling (e.g. a documented d/b/a) — cognee's runtime matches against
    OWL fragments, so the fragment must exist the first time a document
    produces the name."""
    if not path.exists():
        return {}
    aliases: dict[tuple[str, str], dict[str, str]] = {}
    for row in read_csv_rows(path):
        cls = row["class"].strip()
        if cls not in CLASSES:
            raise ValueError(f"aliases.csv: unknown class {cls!r} for alias {row['alias']!r}")
        aliases[(cls, normalize_key(row["alias"]))] = {
            "spelling": row["alias"].strip(),
            "master": normalize_key(row["master_name"]),
        }
    return aliases


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


def _match(candidate_key: str, lookup: dict[str, tuple[str, str]], fuzzy: bool = True) -> tuple[str, str, float] | None:
    if candidate_key in lookup:
        source, key = lookup[candidate_key]
        return source, key, 1.0
    # Short keys are exact-only: at difflib 0.9 a six-char name still reaches
    # a one-letter-different master ('dwayne' -> 'wayne' county at 0.909).
    if not fuzzy or len(candidate_key) < 8:
        return None
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
    aliases: dict[tuple[str, str], str] | None = None,
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

    alias_map = aliases or {}

    def check(cls: str, key: str, pooled: bool) -> tuple[str, str, float] | None:
        # Hand-curated aliases short-circuit everything, sweep included —
        # they are exact by construction and fail loud on a master typo.
        alias = alias_map.get((cls, key))
        if alias is not None:
            if alias["master"] not in lookups[cls]:
                raise ValueError(
                    f"aliases.csv: master {alias['master']!r} for alias {key!r} "
                    f"not present in the {cls} master export"
                )
            source, master_key = lookups[cls][alias["master"]]
            return f"{source} (alias)", master_key, 1.0
        probe = _strip_county_suffix(key) if cls == "County" else key
        # Counties are short geographic words — exact-only at any length.
        hit = _match(probe, lookups[cls], fuzzy=cls != "County")
        if hit is None and cls == "Well":
            stem = _strip_well_number(probe)
            if stem != probe:
                hit = _match(stem, lookups["WellLease"])
        # Org-prefix verification only for candidates the extractor actually
        # typed as organizations; on untyped sweep names it turned formations
        # and regions into vendors ('three forks', 'south texas').
        if hit is None and pooled and cls in ("Operator", "ServiceVendor"):
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
            hit = check(cls, key, pooled=True)
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
            hit = check(cls, key, pooled=False)
            if hit is not None:
                source, master_key, score = hit
                verified[key] = Verified(spelling, cls, source, master_key, score)
                break

    # Alias rows are hand-curated and master-verified by construction — mint
    # an individual for every row even when no extracted candidate carries
    # the spelling yet (e.g. a documented d/b/a). cognee's runtime matches
    # extracted names against OWL fragments, so the fragment must already
    # exist the first time a document produces the name. This also runs the
    # fail-loud master check on dormant rows, which candidate-driven
    # verification would otherwise never reach.
    for (cls, key), alias in sorted(alias_map.items()):
        if key in verified:
            continue
        source, master_key, score = check(cls, key, pooled=True)
        verified[key] = Verified(alias["spelling"], cls, source, master_key, score)

    return list(verified.values()), unverified


# --- U3: deterministic OWL emission -------------------------------------------

BEGIN_MARKER = "<!-- BEGIN GENERATED INDIVIDUALS — do not hand-edit; regenerate via doc_intel_analysts.graph.individuals -->"
END_MARKER = "<!-- END GENERATED INDIVIDUALS -->"


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def fragment_key(name: str) -> str:
    """URI fragment for an individual. Starts from the matcher key but strips
    '#': the resolver derives keys via uri.split('#')[-1], so a '#' inside a
    fragment collapses the lookup key to its tail ('winston_gatlin_#3h' ->
    '3h') — a garbage entry that also exact-matches junk. Stripping costs the
    exact-hit for '#'-spelled names; the 0.8 runtime fuzzy still reaches them
    (~0.97 similarity)."""
    return normalize_key(name).replace("#", "")


def render_individuals(verified: list[Verified]) -> str:
    """One rdf:Description per individual, sorted by class then fragment for
    stable diffs. The URI fragment carries cognee's match key (KTD2) — minted
    normalized and '#'-free via fragment_key; rdfs:label keeps the document
    spelling for human readers (cognee never consults it). Provenance names
    only the master source table — master_key stays in the gitignored report."""
    lines = []
    seen: set[str] = set()
    for v in sorted(verified, key=lambda v: (v.cls, fragment_key(v.name))):
        fragment = _xml_escape(fragment_key(v.name))
        if not fragment or fragment in seen:
            continue  # '#'-stripping can collide two spellings; first wins
        seen.add(fragment)
        lines.append(f'  <rdf:Description rdf:about="#{fragment}">')
        lines.append(f'    <rdf:type rdf:resource="#{v.cls}"/>')
        lines.append(f"    <rdfs:label>{_xml_escape(v.name)}</rdfs:label>")
        lines.append(f"    <rdfs:comment>verified: {_xml_escape(v.master_source)}</rdfs:comment>")
        lines.append("  </rdf:Description>")
    return "\n".join(lines)


def splice_individuals(ontology_text: str, block: str) -> str:
    """Replace the marked individuals block, preserving everything outside
    byte-for-byte. Refuses to run on missing or duplicated markers."""
    for marker in (BEGIN_MARKER, END_MARKER):
        if ontology_text.count(marker) != 1:
            raise ValueError(
                f"marker not found exactly once in ontology: {marker[:40]}… — "
                "add the BEGIN/END GENERATED INDIVIDUALS markers before </rdf:RDF>"
            )
    head, rest = ontology_text.split(BEGIN_MARKER, 1)
    _, tail = rest.split(END_MARKER, 1)
    return f"{head}{BEGIN_MARKER}\n{block}\n  {END_MARKER}{tail}"


def _main() -> None:  # pragma: no cover — exercised end-to-end, not unit-tested
    import argparse
    import json

    repo = Path(__file__).resolve().parents[6]
    analysts = Path(__file__).resolve().parents[3]
    masters_dir = analysts / ".masters"

    parser = argparse.ArgumentParser(description="Regenerate welldrive.owl named individuals")
    parser.add_argument("--nodes", type=Path, default=masters_dir / "nodes.csv")
    parser.add_argument("--edges", type=Path, default=masters_dir / "edges.csv")
    parser.add_argument("--manifest", type=Path, default=repo / "corpus" / "sample-manifest.csv")
    parser.add_argument("--masters-dir", type=Path, default=masters_dir)
    parser.add_argument("--ontology", type=Path, default=repo / "references" / "ontology" / "welldrive.owl")
    parser.add_argument("--aliases", type=Path, default=repo / "references" / "ontology" / "aliases.csv")
    args = parser.parse_args()

    for path, key in ((args.nodes, "nodes.csv"), (args.edges, "edges.csv")):
        if not path.exists():
            from ..corpus import DERIVED_BUCKET, _s3  # boto3 only on the S3 path

            path.parent.mkdir(parents=True, exist_ok=True)
            _s3.download_file(DERIVED_BUCKET, f"runs/doc-intel/graph/{key}", str(path))

    pools = extract_candidates(args.nodes, args.edges, args.manifest)
    well_master = load_master_csv(args.masters_dir / "gold_dim_well.csv", "gold_dim_well.sql")
    vendor_master = load_master_csv(args.masters_dir / "gold_dim_vendor.csv", "gold_dim_vendor.sql")
    verified, unverified = verify_candidates(pools, well_master, vendor_master, load_aliases(args.aliases))

    report_path = args.masters_dir / "unverified-report.csv"
    with report_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "class", "nearest_master", "score"])
        writer.writeheader()
        writer.writerows(unverified)

    args.ontology.write_text(
        splice_individuals(args.ontology.read_text(encoding="utf-8"), render_individuals(verified)),
        encoding="utf-8",
    )

    by_class: dict[str, int] = {}
    for v in verified:
        by_class[v.cls] = by_class.get(v.cls, 0) + 1
    print(json.dumps({
        "verified": len(verified), "by_class": by_class,
        "unverified": len(unverified), "report": str(report_path),
        "ontology": str(args.ontology),
    }, indent=1))


if __name__ == "__main__":
    _main()
