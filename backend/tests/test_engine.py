from app.engine import resolve, topological_order, validate_graph
from app.seed import DEMO_GRAPH


def test_demo_graph_is_valid():
    assert validate_graph(DEMO_GRAPH) == []
    assert topological_order(DEMO_GRAPH)[0] == "trigger"


def test_cycle_is_rejected():
    graph = {"nodes": [{"id": "a", "type": "trigger"}, {"id": "b", "type": "output"}], "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]}
    assert "cycles" in " ".join(validate_graph(graph))


def test_context_interpolation():
    assert resolve("分类={{agent.category}}", {"agent": {"category": "inquiry"}}) == "分类=inquiry"

