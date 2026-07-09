"""U6 contract tests: CSV serialization survives WellDrive naming."""

import csv
import io

from doc_intel_analysts.graph.export import rows_from_graph, to_csv


def test_names_with_commas_quotes_newlines_round_trip():
    nodes = [("n1", {"type": "Well", "name": 'GOODNIGHT, "SELMA" 2H\nline2', "extra": 1})]
    node_rows, _ = rows_from_graph(nodes, [])
    data = to_csv(["id", "type", "name", "properties"], node_rows).decode()
    parsed = list(csv.DictReader(io.StringIO(data)))
    assert parsed[0]["name"] == 'GOODNIGHT, "SELMA" 2H\nline2'
    assert parsed[0]["type"] == "Well"


def test_properties_round_trip_as_json():
    import json

    nodes = [("n1", {"name": "W", "depth_ft": 24565, "teams": ["A", "B"]})]
    node_rows, _ = rows_from_graph(nodes, [])
    props = json.loads(node_rows[0][3])
    assert props == {"depth_ft": 24565, "teams": ["A", "B"]}


def test_edges_serialize_with_label_and_default_props():
    _, edge_rows = rows_from_graph([], [("a", "b", "operatedBy")])
    assert edge_rows[0][:3] == ["a", "b", "operatedBy"]


def test_edge_label_prefers_properties_relationship_name():
    import json

    # The engine tuple's label is the shared storage-table name, which
    # diverges from the semantic relationship held in properties.
    _, edge_rows = rows_from_graph(
        [], [("a", "b", "turned_to_sales", {"relationship_name": "is_a"})]
    )
    assert edge_rows[0][2] == "is_a"
    # relationship_name stays in props — existing consumers read it there.
    assert json.loads(edge_rows[0][3])["relationship_name"] == "is_a"


def test_empty_graph_exports_headers_only():
    node_rows, edge_rows = rows_from_graph([], [])
    data = to_csv(["id", "type", "name", "properties"], node_rows).decode()
    assert data.strip() == "id,type,name,properties"
    assert edge_rows == []
