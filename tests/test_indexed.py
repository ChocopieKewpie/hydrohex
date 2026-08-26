from __future__ import annotations

from hydrohex.core import compute_flow_directions
from hydrohex.indexed import IndexedDGGSGrid, compute_d6_indexed


def _neighbors(cell: str):
    graph = {
        "a": ("b", "outside-a"),
        "b": ("a", "c"),
        "c": ("b", "d"),
        "d": ("c", "outside-d"),
    }
    return graph[cell]


def _distance(_a: str, _b: str) -> float:
    return 2.0


def test_indexed_d6_matches_reference():
    elevation = {"a": 10.0, "b": 8.0, "c": 7.0, "d": 3.0}
    reference = compute_flow_directions(elevation, _neighbors, _distance)
    grid = IndexedDGGSGrid.build(elevation, _neighbors, _distance)
    indexed = compute_d6_indexed(grid, workers=2, chunk_size=2)

    assert indexed.keys() == reference.keys()
    for cell in elevation:
        assert indexed[cell].flow_to == reference[cell].flow_to
        assert indexed[cell].drop == reference[cell].drop
        assert indexed[cell].distance == reference[cell].distance
        assert indexed[cell].slope == reference[cell].slope


def test_indexed_grid_marks_domain_boundaries():
    elevation = {"a": 10.0, "b": 8.0, "c": 7.0, "d": 3.0}
    grid = IndexedDGGSGrid.build(elevation, _neighbors, _distance)
    assert grid.boundary_cells == {"a", "d"}
    assert grid.neighbor_index.shape == (4, 6)


def test_indexed_d6_preserves_sinks_and_tie_order():
    elevation = {"a": 5.0, "b": 4.0, "c": 4.0}

    def neighbors(cell):
        return {
            "a": ("b", "c"),
            "b": ("a", "c", "outside"),
            "c": ("a", "b", "outside"),
        }[cell]

    grid = IndexedDGGSGrid.build(elevation, neighbors, lambda _a, _b: 1.0)
    result = compute_d6_indexed(grid, workers=2, chunk_size=1)
    assert result["a"].flow_to == "b"
    assert result["b"].flow_to is None
    assert result["c"].flow_to is None


def test_indexed_rejects_too_many_neighbors():
    elevation = {"a": 1.0}

    def neighbors(_cell):
        return tuple(f"x{i}" for i in range(7))

    try:
        IndexedDGGSGrid.build(elevation, neighbors, _distance, max_neighbors=6)
    except ValueError as exc:
        assert "max_neighbors" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_geographic_builder_vectorizes_distances():
    elevation = {"a": 3.0, "b": 2.0}

    def neighbors(cell):
        return {"a": ("b", "outside"), "b": ("a", "outside")}[cell]

    coords = {"a": (0.0, 0.0), "b": (0.0, 0.001)}
    grid = IndexedDGGSGrid.build_geographic(elevation, neighbors, coords.__getitem__)
    distance = grid.neighbor_distance[0, 0]
    assert 111.0 < distance < 112.0
    assert grid.boundary_cells == {"a", "b"}
