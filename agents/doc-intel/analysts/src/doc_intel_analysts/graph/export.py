"""Export the knowledge graph as open nodes/edges CSVs (plan U6, R8/R9).

Primary: the graph engine's get_graph_data() (import path verified against
installed 1.2.2). Fallback: direct Kuzu read via the `kuzu` package cognee
already depends on. If both fail, R8/R9 are blocked — surface, don't ship.

Usage: uv run python -m doc_intel_analysts.graph.export
"""

import asyncio
import csv
import io
import json
import time
from typing import Any

from ..corpus import DERIVED_BUCKET, _s3
from . import runtime

EXPORT_PREFIX = "runs/doc-intel/graph/"


def rows_from_graph(nodes: list[tuple], edges: list[tuple]) -> tuple[list[list], list[list]]:
    """Serialize engine tuples to CSV rows. Properties round-trip as JSON;
    the csv module handles embedded commas/quotes/newlines in entity names."""
    node_rows = []
    for node in nodes:
        node_id, props = node[0], (node[1] if len(node) > 1 else {}) or {}
        props = dict(props)
        node_rows.append([
            str(node_id),
            str(props.pop("type", props.pop("label", ""))),
            str(props.pop("name", props.pop("text", ""))[:500]),
            json.dumps(props, default=str),
        ])
    edge_rows = []
    for edge in edges:
        source, target = edge[0], edge[1]
        label = edge[2] if len(edge) > 2 else ""
        props = (edge[3] if len(edge) > 3 else {}) or {}
        edge_rows.append([str(source), str(target), str(label), json.dumps(dict(props), default=str)])
    return node_rows, edge_rows


def to_csv(header: list[str], rows: list[list]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue().encode()


async def fetch_graph() -> tuple[list[tuple], list[tuple]]:
    runtime.get_cognee()
    try:
        from cognee.infrastructure.databases.graph import get_graph_engine

        engine = await get_graph_engine()
        nodes, edges = await engine.get_graph_data()
        return list(nodes), list(edges)
    except Exception as primary_err:
        # Fallback: read the Kuzu store directly (KTD6).
        try:
            import kuzu

            from .config import SYSTEM_ROOT

            db_dirs = list((SYSTEM_ROOT).rglob("*.kuzu")) + [p for p in SYSTEM_ROOT.rglob("databases/*") if p.is_dir()]
            if not db_dirs:
                raise RuntimeError(f"no kuzu store under {SYSTEM_ROOT}")
            db = kuzu.Database(str(db_dirs[0]))
            conn = kuzu.Connection(db)
            nodes = [(r[0], {"name": r[1]}) for r in conn.execute(
                "MATCH (n) RETURN id(n), coalesce(n.name, '')").get_as_df().itertuples(index=False)]
            edges = [(r[0], r[1], r[2], {}) for r in conn.execute(
                "MATCH (a)-[e]->(b) RETURN id(a), id(b), label(e)").get_as_df().itertuples(index=False)]
            return nodes, edges
        except Exception as fallback_err:
            raise RuntimeError(
                f"R8/R9 BLOCKED — both export paths failed. get_graph_data: {primary_err}; "
                f"kuzu fallback: {fallback_err}. Surface to Rob."
            ) from fallback_err


async def run() -> dict[str, Any]:
    nodes, edges = await fetch_graph()
    node_rows, edge_rows = rows_from_graph(nodes, edges)
    stamp = time.strftime("%Y-%m-%d")
    for name, header, rows in (
        ("nodes.csv", ["id", "type", "name", "properties"], node_rows),
        ("edges.csv", ["source", "target", "label", "properties"], edge_rows),
    ):
        _s3.put_object(
            Bucket=DERIVED_BUCKET, Key=f"{EXPORT_PREFIX}{name}",
            Body=to_csv(header, rows), ContentType="text/csv",
        )
    report = {
        "nodes": len(node_rows), "edges": len(edge_rows),
        "location": f"s3://{DERIVED_BUCKET}/{EXPORT_PREFIX}",
        "stamp": stamp,
    }
    print(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    asyncio.run(run())
