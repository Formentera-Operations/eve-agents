"""U1 contract tests: candidate extraction from graph exports + manifest."""

import io

from doc_intel_analysts.graph.individuals import extract_candidates, normalize_key

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
    # measurement-typed entity lands nowhere
    assert not any("survey_station" in k for pool in pools.values() for k in pool)


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
