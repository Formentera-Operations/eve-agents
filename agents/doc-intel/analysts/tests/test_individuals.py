"""U1/U2 contract tests: candidate extraction + master verification."""

import io

import pytest

from doc_intel_analysts.graph.individuals import (
    extract_candidates,
    load_master_csv,
    normalize_key,
    verify_candidates,
)

NODES = (
    "id,type,name,properties\n"
    "e1,Entity,Scientific Drilling,{}\n"
    "e2,Entity,NEAL 3H ST02,{}\n"
    "e3,Entity,Karnes County,{}\n"
    "e4,Entity,survey station tvd 1628.05,{}\n"
    "e5,Entity,Scientific  Drilling,{}\n"
    "t1,EntityType,organization,{}\n"
    "t2,EntityType,well,{}\n"
    "t3,EntityType,location,{}\n"
    "t4,EntityType,measurement,{}\n"
)

EDGES = (
    "source,target,label,properties\n"
    "e1,t1,is_a,{}\n"
    "e2,t2,is_a,{}\n"
    "e3,t3,is_a,{}\n"
    "e4,t4,is_a,{}\n"
    "e5,t1,is_a,{}\n"
    "e1,e2,performed_on,{}\n"
)

# CRLF endings, like the real manifest written by Python csv.
MANIFEST = (
    "key,asset_team,well,category,entry_type,well_name_meta,bytes,parse_source,parsed_ref\r\n"
    "FP GRIFFIN/BENBROOK UNIT 'D' FED 3H/Drilling/x.pdf,FP GRIFFIN,BENBROOK UNIT 'D' FED 3H,Drilling,Daily Report,BENBROOK,1,tierA,ref\r\n"
    "FP GRIFFIN/BENBROOK UNIT 'D' FED 3H/Geology/y.pdf,FP GRIFFIN,BENBROOK UNIT 'D' FED 3H,Geology,Log,BENBROOK,1,unparsed,\r\n"
)


def _pools(nodes=NODES, edges=EDGES, manifest=MANIFEST):
    return extract_candidates(io.StringIO(nodes), io.StringIO(edges), io.StringIO(manifest))


def test_pools_route_by_entity_type():
    pools = _pools()
    assert "scientific_drilling" in pools["Operator"]
    assert "scientific_drilling" in pools["ServiceVendor"]  # orgs feed both; U2 decides
    assert "neal_3h_st02" in pools["Well"]
    assert "karnes_county" in pools["County"]
    # measurement-typed entity lands in no class pool (only the catch-all sweep)
    assert not any("survey_station" in k for cls in ("Well", "Operator", "ServiceVendor", "County", "AssetTeam") for k in pools[cls])
    assert "survey_station_tvd_1628.05" in pools["_sweep"]


def test_crlf_manifest_yields_asset_teams_and_wells():
    pools = _pools()
    assert pools["AssetTeam"] == {"fp_griffin": "FP GRIFFIN"}
    assert "benbrook_unit_'d'_fed_3h" in pools["Well"]
    # duplicate manifest rows dedupe to one candidate
    assert list(pools["AssetTeam"].values()) == ["FP GRIFFIN"]


def test_entities_without_is_a_edges_are_ignored():
    pools = _pools(edges="source,target,label,properties\ne1,e2,performed_on,{}\n")
    assert pools["Operator"] == {}
    assert "neal_3h_st02" not in pools["Well"]  # only manifest wells remain
    assert "benbrook_unit_'d'_fed_3h" in pools["Well"]


def test_corrupted_label_pools_via_properties_relationship():
    # Pre-fix exports carry the storage-table name in `label`; the semantic
    # relationship lives in properties. Properties win in both directions.
    edges = (
        "source,target,label,properties\n"
        'e1,t1,turned_to_sales,"{""relationship_name"": ""is_a""}"\n'
        'e2,t2,is_a,"{""relationship_name"": ""performed_on""}"\n'
    )
    pools = _pools(edges=edges)
    assert "scientific_drilling" in pools["ServiceVendor"]
    assert "neal_3h_st02" not in pools["Well"]


def test_normalize_matches_cognee_and_preserves_first_spelling():
    # byte-identical to cognee's _uri_to_key/find_closest_match normalization:
    # lower, spaces->underscores, strip — internal double spaces are NOT collapsed
    assert normalize_key("Scientific  Drilling") == "scientific__drilling"
    pools = _pools()
    # e1 and e5 normalize differently (double space) so both survive as candidates
    assert pools["Operator"]["scientific_drilling"] == "Scientific Drilling"
    assert pools["Operator"]["scientific__drilling"] == "Scientific  Drilling"


# --- U2 ---

WELL_MASTER = [
    {"EID": "100001", "API_10": "4225533332", "WELL_NAME": "NEAL 3H ST02",
     "LEASE_NAME": "NEAL", "COMPANY_NAME": "FORMENTERA OPERATIONS, LLC",
     "OPERATOR_NAME": "FORMENTERA OPERATIONS", "STATE": "TX", "COUNTY": "KARNES"},
]

VENDOR_MASTER = [
    {"VENDOR_ID": "V-77", "VENDOR_NAME": "SCIENTIFIC DRILLING INTL",
     "VENDOR_FULL_NAME": "SCIENTIFIC DRILLING INTERNATIONAL, INC."},
]


def _verify(pools):
    return verify_candidates(pools, WELL_MASTER, VENDOR_MASTER)


def test_exact_after_normalization_short_circuits_fuzzy():
    verified, unverified = _verify({"Well": {"neal_3h_st02": "NEAL 3H st02"}})
    (v,) = verified
    assert (v.cls, v.master_source, v.master_key, v.score) == ("Well", "gold_dim_well", "100001", 1.0)
    assert unverified == []


def test_fuzzy_at_or_above_cutoff_verifies_with_score():
    # "scientific drilling intl." vs master "SCIENTIFIC DRILLING INTL" — ratio >= 0.9
    verified, unverified = _verify({"ServiceVendor": {"scientific_drilling_intl.": "Scientific Drilling Intl."}})
    (v,) = verified
    assert v.master_source == "gold_dim_vendor" and v.master_key == "V-77"
    assert 0.9 <= v.score < 1.0
    assert unverified == []


def test_below_cutoff_lands_in_report_with_nearest_master():
    verified, unverified = _verify({"ServiceVendor": {"nabors_b-23": "Nabors B-23"}})
    assert verified == []
    (u,) = unverified
    assert u["class"] == "ServiceVendor" and u["nearest_master"] and float(u["score"]) < 0.9


def test_county_suffix_tolerated_and_asset_team_verified_by_manifest():
    verified, _ = _verify({
        "County": {"karnes_county": "Karnes County"},
        "AssetTeam": {"fp_griffin": "FP GRIFFIN"},
    })
    by_cls = {v.cls: v for v in verified}
    assert by_cls["County"].master_key == "KARNES"
    assert by_cls["AssetTeam"].master_source == "manifest"


def test_missing_masters_csv_fails_loud(tmp_path):
    with pytest.raises(FileNotFoundError, match="snow sql export"):
        load_master_csv(tmp_path / "gold_dim_well.csv", "gold_dim_well.sql")


# --- U3 ---

from doc_intel_analysts.graph.individuals import (  # noqa: E402
    BEGIN_MARKER,
    END_MARKER,
    Verified,
    render_individuals,
    splice_individuals,
)

ONTOLOGY_SHELL = (
    '<?xml version="1.0"?>\n<rdf:RDF>\n  <owl:Class rdf:about="#Well"/>\n'
    f"  {BEGIN_MARKER}\n  {END_MARKER}\n</rdf:RDF>\n"
)

SAMPLE = [
    Verified("NEAL 3H ST02", "Well", "gold_dim_well", "100001", 1.0),
    Verified("Scientific Drilling Intl.", "ServiceVendor", "gold_dim_vendor", "V-77", 0.96),
    Verified("BENBROOK UNIT 'D' FED 3H", "Well", "gold_dim_well (lease)", "111556", 0.95),
    Verified("H&P Drilling", "ServiceVendor", "gold_dim_vendor", "V-9", 1.0),
    Verified("WINSTON GATLIN #3H", "Well", "gold_dim_well", "111818", 0.97),
]


def _uri_to_key(uri: str) -> str:
    """Reimplementation of cognee 1.2.2 RDFLibOntologyResolver._uri_to_key —
    the round-trip arbiter pinning KTD2 against cognee upgrades."""
    name = uri.split("#")[-1] if "#" in uri else uri.rstrip("/").split("/")[-1]
    return name.lower().replace(" ", "_").strip()


def test_emission_is_deterministic():
    assert render_individuals(SAMPLE) == render_individuals(list(reversed(SAMPLE)))


def test_round_trip_fragment_equals_cognee_match_key():
    import difflib
    import re

    block = render_individuals(SAMPLE)
    fragments = re.findall(r'rdf:about="#([^"]+)"', block)
    assert len(fragments) == len(SAMPLE)
    keys = {normalize_key(v.name) for v in SAMPLE}
    for frag in fragments:
        # un-escape the XML attribute back to the raw fragment
        raw = frag.replace("&amp;", "&").replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">")
        assert "#" not in raw, "a '#' inside a fragment collapses the resolver key to its tail"
        base = "https://formenteraops.com/ontology/welldrive"
        assert _uri_to_key(f"{base}#{raw}") == raw, "fragment must survive the resolver's key derivation"
        # runtime match still reaches the doc spelling: exact, or fuzzy >= 0.8
        assert raw in keys or max(
            difflib.SequenceMatcher(None, raw, k).ratio() for k in keys
        ) >= 0.8


def test_number_sign_names_mint_hash_free_fragments():
    block = render_individuals([Verified("WINSTON GATLIN #3H", "Well", "gold_dim_well", "1", 1.0)])
    assert 'rdf:about="#winston_gatlin_3h"' in block
    assert "winston_gatlin_#3h" not in block
    # label still carries the document spelling
    assert "<rdfs:label>WINSTON GATLIN #3H</rdfs:label>" in block


def test_splice_preserves_outside_bytes_and_replaces_block():
    once = splice_individuals(ONTOLOGY_SHELL, render_individuals(SAMPLE))
    assert once.startswith('<?xml version="1.0"?>\n<rdf:RDF>\n  <owl:Class rdf:about="#Well"/>')
    assert once.endswith("</rdf:RDF>\n")
    assert "NEAL 3H ST02" in once
    # regeneration replaces, never appends
    twice = splice_individuals(once, render_individuals(SAMPLE))
    assert twice == once


def test_splice_refuses_missing_or_duplicate_markers():
    with pytest.raises(ValueError, match="marker"):
        splice_individuals("<rdf:RDF></rdf:RDF>", "x")
    with pytest.raises(ValueError, match="marker"):
        splice_individuals(ONTOLOGY_SHELL + BEGIN_MARKER, "x")


def test_provenance_names_table_only_never_master_key():
    block = render_individuals(SAMPLE)
    assert "gold_dim_well" in block and "gold_dim_vendor" in block
    assert "100001" not in block and "V-77" not in block and "V-9" not in block


def test_rendered_block_is_parseable_rdf():
    import rdflib

    doc = (
        '<?xml version="1.0"?>\n'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"\n'
        '         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"\n'
        '         xmlns:owl="http://www.w3.org/2002/07/owl#"\n'
        '         xml:base="https://formenteraops.com/ontology/welldrive"\n'
        '         xmlns="https://formenteraops.com/ontology/welldrive#">\n'
        '  <owl:Class rdf:about="#Well"/>\n  <owl:Class rdf:about="#ServiceVendor"/>\n'
        + render_individuals(SAMPLE)
        + "\n</rdf:RDF>"
    )
    g = rdflib.Graph()
    g.parse(data=doc, format="xml")
    ns = "https://formenteraops.com/ontology/welldrive#"
    wells = list(g.subjects(rdflib.RDF.type, rdflib.URIRef(ns + "Well")))
    assert len(wells) == 3  # the three Well individuals; class declarations are typed owl:Class


# --- U4 iteration: sweep precision guards ---

def test_short_keys_are_exact_only_no_fuzzy_county():
    # 'dwayne' must NOT verify against county 'WAYNE' (difflib 0.909)
    wm = [{"EID": "1", "WELL_NAME": "X 1H", "LEASE_NAME": "X",
           "COMPANY_NAME": "C", "OPERATOR_NAME": "C", "STATE": "ND", "COUNTY": "WAYNE"}]
    verified, _ = verify_candidates({"_sweep": {"dwayne": "dwayne"}}, wm, [])
    assert verified == []


def test_sweep_never_uses_org_prefix():
    # 'three forks' (a formation) must not become a vendor via prefix on sweep
    vm = [{"VENDOR_ID": "V1", "VENDOR_NAME": "THREE FORKS SERVICES LLC", "VENDOR_FULL_NAME": ""}]
    verified, _ = verify_candidates({"_sweep": {"three_forks": "three forks"}}, [], vm)
    assert verified == []
    # but a pooled (organization-typed) candidate still verifies via prefix
    verified, _ = verify_candidates({"ServiceVendor": {"three_forks": "three forks"}}, [], vm)
    assert [v.master_key for v in verified] == ["V1"]
