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
