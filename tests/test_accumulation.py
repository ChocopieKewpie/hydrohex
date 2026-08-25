import pytest

from hydrohex.accumulation import FlowCycleError, accumulate, boundary_cells
from hydrohex.graph import FlowEdge, WeightedFlowGraph


def graph(cells, edges):
    return WeightedFlowGraph.from_edges(cells, [FlowEdge(*edge) for edge in edges])


def test_d6_chain_accumulates_counts():
    g = graph(["a", "b", "c"], [("a", "b", 1.0), ("b", "c", 1.0)])
    result = accumulate(g)
    assert result.values == pytest.approx({"a": 1.0, "b": 2.0, "c": 3.0})


def test_convergence_accumulates_all_sources():
    g = graph(
        ["a", "b", "c", "d"],
        [("a", "d", 1.0), ("b", "d", 1.0), ("c", "d", 1.0)],
    )
    result = accumulate(g)
    assert result["d"] == pytest.approx(4.0)


def test_dinf_split_and_reconvergence_conserves_mass():
    g = graph(
        ["a", "b", "c", "d"],
        [
            ("a", "b", 0.25),
            ("a", "c", 0.75),
            ("b", "d", 1.0),
            ("c", "d", 1.0),
        ],
    )
    result = accumulate(g)
    assert result["b"] == pytest.approx(1.25)
    assert result["c"] == pytest.approx(1.75)
    assert result["d"] == pytest.approx(4.0)


def test_physical_area_uses_supplied_local_contributions():
    g = graph(["a", "b", "c"], [("a", "b", 1.0), ("b", "c", 1.0)])
    result = accumulate(g, {"a": 10.0, "b": 20.0, "c": 30.0})
    assert result.values == pytest.approx({"a": 10.0, "b": 30.0, "c": 60.0})


def test_edge_contamination_propagates_only_downstream():
    g = graph(
        ["a", "b", "c", "x"],
        [("a", "b", 1.0), ("b", "c", 1.0)],
    )
    result = accumulate(g, edge_contaminated_sources={"a"})
    assert result.edge_contaminated == {"a": True, "b": True, "c": True, "x": False}


def test_cycle_detection_fails_loudly():
    g = graph(["a", "b", "c"], [("a", "b", 1.0), ("b", "c", 1.0), ("c", "a", 1.0)])
    with pytest.raises(FlowCycleError):
        accumulate(g)


def test_boundary_cells_detect_missing_neighbor():
    topology = {"a": ["b", "outside"], "b": ["a"]}
    assert boundary_cells({"a", "b"}, lambda cell: topology[cell]) == {"a"}


def test_graph_rejects_nonconservative_fraction_sum():
    with pytest.raises(ValueError, match="sum"):
        graph(["a", "b", "c"], [("a", "b", 0.2), ("a", "c", 0.7)])


def test_single_basin_sink_receives_total_physical_area():
    g = graph(
        ["a", "b", "c", "d"],
        [("a", "c", 1.0), ("b", "c", 1.0), ("c", "d", 1.0)],
    )
    areas = {"a": 11.0, "b": 12.0, "c": 13.0, "d": 14.0}
    result = accumulate(g, areas)
    assert result["d"] == pytest.approx(sum(areas.values()))


def test_parallel_accumulation_matches_serial_on_wide_convergence():
    sources = [f"s{i}" for i in range(600)]
    cells = [*sources, "sink"]
    edges = [(source, "sink", 1.0) for source in sources]
    g = graph(cells, edges)

    serial = accumulate(g, workers=1)
    parallel = accumulate(g, workers=4, parallel_min_front_size=32)

    assert parallel.values == pytest.approx(serial.values)
    assert parallel.edge_contaminated == serial.edge_contaminated
    assert parallel.stats is not None
    assert parallel.stats.parallel_fronts >= 1
    assert parallel.stats.max_front_width == len(sources)
    assert parallel.stats.processed_cells == len(cells)


def test_parallel_dinf_split_reconvergence_matches_serial():
    sources = [f"s{i}" for i in range(400)]
    left = [f"l{i}" for i in range(20)]
    right = [f"r{i}" for i in range(20)]
    cells = [*sources, *left, *right, "sink"]
    edges = []
    for i, source in enumerate(sources):
        edges.append((source, left[i % len(left)], 0.35))
        edges.append((source, right[i % len(right)], 0.65))
    edges.extend((cell, "sink", 1.0) for cell in left)
    edges.extend((cell, "sink", 1.0) for cell in right)
    g = graph(cells, edges)
    areas = {cell: 100.0 + (i % 7) for i, cell in enumerate(cells)}

    serial = accumulate(g, areas, workers=1)
    parallel = accumulate(g, areas, workers=6, parallel_min_front_size=16)

    assert parallel.values == pytest.approx(serial.values, rel=1e-12, abs=1e-9)
    assert parallel["sink"] == pytest.approx(sum(areas.values()))
    assert parallel.stats is not None
    assert parallel.stats.parallel_fronts >= 1


def test_parallel_contamination_matches_serial():
    sources = [f"s{i}" for i in range(300)]
    cells = [*sources, "mid", "sink"]
    edges = [(source, "mid", 1.0) for source in sources] + [("mid", "sink", 1.0)]
    g = graph(cells, edges)
    contaminated_sources = {"s17", "s92"}

    serial = accumulate(g, workers=1, edge_contaminated_sources=contaminated_sources)
    parallel = accumulate(
        g,
        workers=4,
        parallel_min_front_size=16,
        edge_contaminated_sources=contaminated_sources,
    )

    assert parallel.values == pytest.approx(serial.values)
    assert parallel.edge_contaminated == serial.edge_contaminated
    assert parallel.edge_contaminated["mid"] is True
    assert parallel.edge_contaminated["sink"] is True
