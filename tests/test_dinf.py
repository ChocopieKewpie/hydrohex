import math

import pytest

from hydrohex.dinf import dinf_flow_direction, ordered_neighbors


ANGLES = {
    "e": 0.0,
    "ne": math.pi / 3,
    "nw": 2 * math.pi / 3,
    "w": math.pi,
    "sw": 4 * math.pi / 3,
    "se": 5 * math.pi / 3,
}
XY = {name: (math.cos(a), math.sin(a)) for name, a in ANGLES.items()}
GRAPH = {"c": ["sw", "e", "nw", "se", "ne", "w"]}


def neighbors(cell):
    return GRAPH[cell]


def xy(cell, origin):
    assert origin == "c"
    return XY[cell]


def test_neighbors_are_ordered_geometrically_not_by_input_order():
    assert ordered_neighbors("c", neighbors, xy) == ["e", "ne", "nw", "w", "sw", "se"]


def test_plane_between_two_hex_neighbors_splits_flow_evenly():
    # z = 100 - 10 * (cos(30)*x + sin(30)*y), so the downslope
    # direction lies exactly halfway between east (0 deg) and NE (60 deg).
    theta = math.radians(30.0)
    dem = {"c": 100.0}
    for name, (x, y) in XY.items():
        dem[name] = 100.0 - 10.0 * (math.cos(theta) * x + math.sin(theta) * y)

    result = dinf_flow_direction("c", dem, neighbors, xy)

    assert result.direction_rad == pytest.approx(theta)
    assert result.slope == pytest.approx(10.0)
    assert {result.receiver_1, result.receiver_2} == {"e", "ne"}
    assert result.fraction_1 == pytest.approx(0.5)
    assert result.fraction_2 == pytest.approx(0.5)
    assert sum(f for _, f in result.receivers) == pytest.approx(1.0)


def test_direction_on_neighbor_ray_collapses_to_one_receiver():
    dem = {"c": 100.0}
    for name, (x, _y) in XY.items():
        dem[name] = 100.0 - 10.0 * x

    result = dinf_flow_direction("c", dem, neighbors, xy)

    assert result.receiver_1 == "e"
    assert result.receiver_2 is None
    assert result.fraction_1 == pytest.approx(1.0)
    assert result.direction_rad == pytest.approx(0.0)


def test_closed_depression_is_sink():
    dem = {"c": 0.0, **{name: 1.0 for name in XY}}
    result = dinf_flow_direction("c", dem, neighbors, xy)
    assert result.sink
    assert result.direction_rad is None
    assert result.slope == 0.0
    assert result.receivers == ()


def test_missing_boundary_neighbors_are_ignored():
    dem = {"c": 10.0, "e": 5.0}
    result = dinf_flow_direction("c", dem, neighbors, xy)
    assert result.receiver_1 == "e"
    assert result.fraction_1 == pytest.approx(1.0)
