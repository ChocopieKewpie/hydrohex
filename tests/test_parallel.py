import pytest

from hydrohex.core import compute_flow_directions
from hydrohex.parallel import resolve_workers


def test_parallel_d6_matches_serial():
    topology = {
        "a": ["b"],
        "b": ["a", "c"],
        "c": ["b", "d"],
        "d": ["c"],
    }
    dem = {"a": 4.0, "b": 3.0, "c": 2.0, "d": 1.0}
    distance = lambda _a, _b: 1.0
    serial = compute_flow_directions(dem, topology.__getitem__, distance, workers=1)
    threaded = compute_flow_directions(dem, topology.__getitem__, distance, workers=3)
    assert threaded == serial


def test_worker_validation():
    assert resolve_workers(1) == 1
    assert resolve_workers(0) >= 1
    with pytest.raises(ValueError):
        resolve_workers(-1)
