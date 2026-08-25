import pytest

h3 = pytest.importorskip("h3")

from hydrohex.selftest import run_self_test


def test_complete_toolbox_self_test():
    # Small enough for CI; exercises deterministic terrain, smoothing, pit detection,
    # fill, breach, hybrid conditioning, D6, Dinf, graphs and accumulation.
    summary = run_self_test(workers=2, include_gis=False)
    assert summary["status"] == "ok"
    assert summary["cells"] > 10
    assert summary["smoothed_modified_cells"] > 0
