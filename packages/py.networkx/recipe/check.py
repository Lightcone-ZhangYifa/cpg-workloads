#!/usr/bin/env python3
"""Installed functional check for networkx; no network access required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(nx, work):
    """Check small graph answers and graph-specific negative cases."""
    graph = nx.DiGraph()
    graph.add_weighted_edges_from([("a", "b", 2), ("b", "c", 3), ("a", "c", 9)])
    require(nx.shortest_path(graph, "a", "c", weight="weight") == ["a", "b", "c"], "Weighted path mismatch")
    require(nx.shortest_path_length(graph, "a", "c", weight="weight") == 5, "Distance mismatch")
    order = list(nx.topological_sort(graph))
    require(order == ["a", "b", "c"], "Dependency order mismatch")
    rebuilt = nx.node_link_graph(nx.node_link_data(graph))
    require(nx.is_isomorphic(graph, rebuilt, edge_match=lambda a,b:a==b), "Graph interchange mismatch")
    raises(nx.NetworkXNoPath, lambda: nx.shortest_path(graph, "c", "a"), "Missing path was accepted")
    graph.add_edge("c", "a")
    raises(nx.NetworkXUnfeasible, lambda: list(nx.topological_sort(graph)), "Cyclic dependency order was accepted")
    return {"checks": ["weighted-path", "topological-sort", "node-link-roundtrip", "no-path", "cycle"]}

if __name__ == "__main__":
    raise SystemExit(main('networkx', 'networkx', functional))
