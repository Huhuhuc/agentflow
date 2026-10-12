from app.engine import pick_terminal, resolve, terminal_node_ids, topological_order, validate_graph
from app.seed import DEMO_GRAPH


def test_demo_graph_is_valid():
    assert validate_graph(DEMO_GRAPH) == []
    assert topological_order(DEMO_GRAPH)[0] == "trigger"


def test_cycle_is_rejected():
    graph = {"nodes": [{"id": "a", "type": "trigger"}, {"id": "b", "type": "output"}], "edges": [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]}
    assert "cycles" in " ".join(validate_graph(graph))


def test_context_interpolation():
    assert resolve("分类={{agent.category}}", {"agent": {"category": "inquiry"}}) == "分类=inquiry"


def test_terminal_is_derived_from_edges_not_declaration_order():
    """终点由“无出边”推导，与 nodes 数组顺序无关（旧实现取 nodes[-1] 会取错）。"""
    graph = {
        "nodes": [
            {"id": "out", "type": "output"},  # 声明在最前，但它才是真正的终点
            {"id": "trigger", "type": "trigger"},
            {"id": "agent", "type": "agent"},
        ],
        "edges": [
            {"source": "trigger", "target": "agent"},
            {"source": "agent", "target": "out"},
        ],
    }
    assert terminal_node_ids(graph) == ["out"]
    assert graph["nodes"][-1]["id"] == "agent"  # 旧逻辑会误判成 agent
    order = topological_order(graph)
    assert pick_terminal(graph, order, ["trigger", "agent", "out"]) == "out"


def test_terminal_picks_the_branch_that_actually_ran():
    """条件分支下有多个终点时，取实际走通那条分支的结果。"""
    graph = {
        "nodes": [
            {"id": "trigger", "type": "trigger"},
            {"id": "cond", "type": "condition"},
            {"id": "notify", "type": "notification"},
            {"id": "out", "type": "output"},
        ],
        "edges": [
            {"source": "trigger", "target": "cond"},
            {"source": "cond", "target": "notify", "label": "true"},
            {"source": "cond", "target": "out", "label": "false"},
        ],
    }
    assert set(terminal_node_ids(graph)) == {"notify", "out"}
    order = topological_order(graph)
    # out 分支被跳过 → 结果应取 notify，而不是数组末尾的 out
    assert pick_terminal(graph, order, ["trigger", "cond", "notify"]) == "notify"
    # 反之亦然
    assert pick_terminal(graph, order, ["trigger", "cond", "out"]) == "out"


def test_demo_graph_terminal_has_no_outgoing_edge():
    """演示工作流的终点必须真的没有出边。"""
    terminals = terminal_node_ids(DEMO_GRAPH)
    assert terminals
    sources = {edge["source"] for edge in DEMO_GRAPH["edges"]}
    assert all(node_id not in sources for node_id in terminals)

