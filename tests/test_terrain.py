import pytest

from hydrohex.terrain import (
    breach_depressions,
    condition_dem,
    find_flats,
    find_pits,
    priority_flood_fill,
    smooth_dem,
)


LINE = {
    "a": ["outside_a", "b"],
    "b": ["a", "c"],
    "c": ["b", "d"],
    "d": ["c", "e"],
    "e": ["d", "outside_e"],
}


def neighbors(cell):
    return LINE[cell]


def unit_distance(_a, _b):
    return 1.0


def test_priority_flood_fills_internal_depression():
    dem = {"a": 0.0, "b": 5.0, "c": 1.0, "d": 5.0, "e": 0.0}
    assert find_pits(dem, neighbors) == {"c"}
    result = priority_flood_fill(dem, neighbors)
    assert result.elevation["c"] == pytest.approx(5.0)
    assert result.diagnostics["fill_depth_m"]["c"] == pytest.approx(4.0)
    assert "c" in result.modified_cells


def test_breach_carves_monotonic_escape_from_pit():
    dem = {"a": 0.0, "b": 5.0, "c": 1.0, "d": 5.0, "e": 0.0}
    result = breach_depressions(
        dem,
        neighbors,
        distance=unit_distance,
        min_slope=0.1,
        max_breach_depth_m=10.0,
    )
    assert result.elevation["b"] < dem["c"] or result.elevation["d"] < dem["c"]
    assert any(v > 0 for v in result.diagnostics["breach_depth_m"].values())


def test_hybrid_conditions_depression_and_preserves_domain():
    dem = {"a": 0.0, "b": 5.0, "c": 1.0, "d": 5.0, "e": 0.0}
    result = condition_dem(
        dem,
        neighbors,
        method="hybrid",
        distance=unit_distance,
        min_slope=0.01,
        max_fill_depth_m=0.5,
        max_breach_depth_m=10.0,
    )
    assert set(result.elevation) == set(dem)
    assert {"fill_depth_m", "breach_depth_m"}.issubset(result.diagnostics)
    assert result.modified_cells


def test_bilateral_smoothing_preserves_large_step_better_than_mean():
    topology = {
        "a": ["b"],
        "b": ["a", "c"],
        "c": ["b"],
    }
    dem = {"a": 0.0, "b": 0.0, "c": 100.0}
    mean = smooth_dem(dem, topology.__getitem__, method="mean")
    bilateral = smooth_dem(
        dem,
        topology.__getitem__,
        method="bilateral",
        distance=unit_distance,
        spatial_sigma=2.0,
        elevation_sigma=5.0,
    )
    assert bilateral.elevation["b"] < mean.elevation["b"]
    assert bilateral.elevation["c"] > mean.elevation["c"]


def test_parallel_smoothing_matches_serial():
    dem = {"a": 0.0, "b": 2.0, "c": 5.0, "d": 3.0, "e": 0.0}
    serial = smooth_dem(dem, neighbors, method="mean", workers=1)
    threaded = smooth_dem(dem, neighbors, method="mean", workers=3)
    assert threaded.elevation == pytest.approx(serial.elevation)


def test_find_flats_detects_equal_neighbors():
    dem = {"a": 0.0, "b": 1.0, "c": 1.0, "d": 2.0, "e": 0.0}
    flats = find_flats(dem, neighbors)
    assert {"b", "c"}.issubset(flats)
