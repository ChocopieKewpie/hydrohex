import pytest

from hydrohex.core import compute_flow_directions, flow_direction


GRAPH = {
    "c": ["e", "w", "n", "s", "ne", "sw"],
    "e": ["c"], "w": ["c"], "n": ["c"], "s": ["c"], "ne": ["c"], "sw": ["c"],
}


def neighbors(cell):
    return GRAPH[cell]


def unit_distance(_a, _b):
    return 1.0


def test_steepest_downslope_neighbor_is_selected():
    dem = {"c": 100, "e": 90, "w": 99, "n": 98, "s": 97, "ne": 96, "sw": 95}
    r = flow_direction("c", dem, neighbors, unit_distance)
    assert r.flow_to == "e"
    assert r.drop == pytest.approx(10.0)
    assert r.slope == pytest.approx(10.0)


def test_slope_not_raw_drop_controls_choice():
    dem = {"c": 100, "e": 90, "w": 94, "n": 101, "s": 101, "ne": 101, "sw": 101}
    distances = {("c", "e"): 10.0, ("c", "w"): 2.0}
    def d(a, b):
        return distances.get((a, b), 1.0)
    r = flow_direction("c", dem, neighbors, d)
    assert r.flow_to == "w"
    assert r.slope == pytest.approx(3.0)


def test_sink_returns_none():
    dem = {"c": 1, "e": 2, "w": 2, "n": 2, "s": 2, "ne": 2, "sw": 2}
    r = flow_direction("c", dem, neighbors, unit_distance)
    assert r.flow_to is None
    assert r.slope == 0.0


def test_missing_neighbor_is_ignored():
    dem = {"c": 10, "e": 5}
    r = flow_direction("c", dem, neighbors, unit_distance)
    assert r.flow_to == "e"


def test_nonpositive_distance_rejected():
    dem = {"c": 10, "e": 5}
    with pytest.raises(ValueError):
        flow_direction("c", dem, neighbors, lambda _a, _b: 0.0)


def test_compute_all_cells():
    dem = {"c": 10, "e": 5}
    graph = {"c": ["e"], "e": ["c"]}
    out = compute_flow_directions(dem, graph.__getitem__, unit_distance)
    assert out["c"].flow_to == "e"
    assert out["e"].flow_to is None
