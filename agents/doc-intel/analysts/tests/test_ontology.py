"""U2 contract tests: the ontology parses and covers the promised vocabulary."""

import json
from pathlib import Path

import rdflib

REPO = Path(__file__).resolve().parents[4]
ONTOLOGY = REPO / "references" / "ontology" / "welldrive.owl"
NS = "https://formenteraops.com/ontology/welldrive#"
OWL_CLASS = rdflib.URIRef("http://www.w3.org/2002/07/owl#Class")
RDF_TYPE = rdflib.RDF.type


def _graph() -> rdflib.Graph:
    g = rdflib.Graph()
    g.parse(ONTOLOGY)
    return g


def test_parses_and_has_core_classes():
    g = _graph()
    classes = {str(s) for s in g.subjects(RDF_TYPE, OWL_CLASS)}
    for name in ("Well", "Operator", "ServiceVendor", "Formation", "County", "AssetTeam", "Event", "DocumentClass"):
        assert NS + name in classes, f"missing core class {name}"


def test_every_analyst_class_has_a_document_group():
    g = _graph()
    classes = {str(s) for s in g.subjects(RDF_TYPE, OWL_CLASS)}
    analyst = json.loads((REPO / "references" / "analyst-classes.json").read_text())["classes"]
    assert len(analyst) == 7
    for cls in analyst:
        # drilling_ops_analyst -> DrillingOpsDocument
        group = "".join(w.title() for w in cls["name"].replace("_analyst", "").split("_"))
        assert NS + group + "Document" in classes, f"missing group for {cls['name']}"


def test_key_object_properties_have_domain_and_range():
    g = _graph()
    for prop in ("operatedBy", "servicedBy", "occurredOn"):
        uri = rdflib.URIRef(NS + prop)
        assert (uri, rdflib.RDFS.domain, None) in g, f"{prop} missing domain"
        assert (uri, rdflib.RDFS.range, None) in g, f"{prop} missing range"


def test_entry_type_count_matches_manifest_vocabulary():
    g = _graph()
    analyst = json.loads((REPO / "references" / "analyst-classes.json").read_text())["classes"]
    expected = sum(len(c["entry_types"]) for c in analyst)
    labels = list(g.objects(None, rdflib.RDFS.label))
    assert len(labels) == expected, f"{len(labels)} entry-type leaves vs {expected} in the table"
