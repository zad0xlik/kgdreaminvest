"""Graph visualization routes."""

from flask import Blueprint, jsonify

from src.database import db_conn, init_db, bootstrap_if_empty
from src.backend.services import kind_color, edge_color

bp = Blueprint("graph", __name__)


@bp.route("/graph-data")
def graph_data():
    """Return nodes and edges for vis-network visualization."""
    init_db()
    bootstrap_if_empty()
    
    with db_conn() as conn:
        node_rows = conn.execute("""
          SELECT node_id, kind, label, score, degree
          FROM nodes
          ORDER BY (degree*1.0 + score*5.0) DESC
          LIMIT 160
        """).fetchall()
        
        node_ids = {r["node_id"] for r in node_rows}
        nodes = [{
            "id": r["node_id"],
            "label": r["label"],
            "value": int(r["degree"]) + 7,
            "title": f"{r['kind']} | deg={r['degree']} score={float(r['score']):.2f}",
            "color": {"border": kind_color(r["kind"]), "background": "#0b1220"},
        } for r in node_rows]

        edge_rows = conn.execute(
            "SELECT edge_id, node_a, node_b, weight, top_channel FROM edges ORDER BY weight DESC LIMIT 520"
        ).fetchall()
        
        edges = []
        for e in edge_rows:
            if e["node_a"] in node_ids and e["node_b"] in node_ids:
                edges.append({
                    "id": int(e["edge_id"]),
                    "from": e["node_a"],
                    "to": e["node_b"],
                    "value": max(1, min(8, int(float(e["weight"]) * 3))),
                    "title": f"w={float(e['weight']):.2f} top={e['top_channel'] or ''}",
                    "color": {"color": edge_color(e["top_channel"] or "")},
                })
    
    return jsonify({"nodes": nodes, "edges": edges})


@bp.route("/node/<path:node_id>")
def node_detail(node_id: str):
    """Get detailed information about a specific node."""
    init_db()
    bootstrap_if_empty()
    
    with db_conn() as conn:
        n = conn.execute("SELECT * FROM nodes WHERE node_id=?", (node_id,)).fetchone()
        if not n:
            return jsonify({"error": "node not found"}), 404
        
        edges = conn.execute("""
          SELECT edge_id, node_a, node_b, weight, top_channel
          FROM edges
          WHERE node_a=? OR node_b=?
          ORDER BY weight DESC
          LIMIT 20
        """, (node_id, node_id)).fetchall()
        
        out_edges = []
        for e in edges:
            other = e["node_b"] if e["node_a"] == node_id else e["node_a"]
            on = conn.execute("SELECT label FROM nodes WHERE node_id=?", (other,)).fetchone()
            out_edges.append({
                "edge_id": int(e["edge_id"]),
                "neighbor": other,
                "neighbor_label": (on["label"] if on else other),
                "weight": float(e["weight"]),
                "top_channel": e["top_channel"] or ""
            })
        
        return jsonify({
            "node_id": n["node_id"],
            "kind": n["kind"],
            "label": n["label"],
            "description": n["description"] or "",
            "score": float(n["score"]),
            "degree": int(n["degree"]),
            "edges": out_edges
        })


@bp.route("/edge/<int:edge_id>")
def edge_detail(edge_id: int):
    """Get detailed information about a specific edge."""
    init_db()
    bootstrap_if_empty()
    
    with db_conn() as conn:
        e = conn.execute("SELECT * FROM edges WHERE edge_id=?", (edge_id,)).fetchone()
        if not e:
            return jsonify({"error": "edge not found"}), 404
        
        a = e["node_a"]
        b = e["node_b"]
        la = conn.execute("SELECT label FROM nodes WHERE node_id=?", (a,)).fetchone()
        lb = conn.execute("SELECT label FROM nodes WHERE node_id=?", (b,)).fetchone()
        ch = conn.execute(
            "SELECT channel, strength FROM edge_channels WHERE edge_id=? ORDER BY strength DESC", 
            (edge_id,)
        ).fetchall()
        
        return jsonify({
            "edge_id": int(edge_id),
            "a": a, 
            "b": b,
            "a_label": (la["label"] if la else a),
            "b_label": (lb["label"] if lb else b),
            "weight": float(e["weight"]),
            "top_channel": e["top_channel"] or "",
            "channels": [{"channel": r["channel"], "strength": float(r["strength"])} for r in ch],
        })
