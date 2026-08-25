import pytest

from hydrohex.core import FlowResult
from hydrohex.dinf import DInfFlowResult
from hydrohex.graph import graph_from_d6, graph_from_dinf


def test_d6_results_convert_to_unit_edges():
    results = {
        "a": FlowResult("a", "b", 1.0, 1.0, 1.0),
        "b": FlowResult("b", None, 0.0, 0.0, 0.0),
    }
    graph = graph_from_d6(results)
    edge = graph.outgoing["a"][0]
    assert (edge.receiver, edge.fraction) == ("b", 1.0)
    assert graph.outgoing["b"] == ()


def test_dinf_results_convert_to_weighted_edges():
    results = {
        "a": DInfFlowResult("a", 0.5, 1.0, "b", 0.4, "c", 0.6),
        "b": DInfFlowResult("b", None, 0.0, None, 0.0, None, 0.0),
        "c": DInfFlowResult("c", None, 0.0, None, 0.0, None, 0.0),
    }
    graph = graph_from_dinf(results)
    edges = graph.outgoing["a"]
    assert [e.receiver for e in edges] == ["b", "c"]
    assert [e.fraction for e in edges] == pytest.approx([0.4, 0.6])
