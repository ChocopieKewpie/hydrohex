"""Opt-in real-terrain regression against the live USGS 3DEP service.

Run with:
    DGGS_FLOW_RUN_NETWORK_TESTS=1 pytest tests/test_real_dem.py -q
"""

import os

import pytest

pytestmark = pytest.mark.network


@pytest.mark.skipif(
    os.environ.get("DGGS_FLOW_RUN_NETWORK_TESTS") != "1",
    reason="set DGGS_FLOW_RUN_NETWORK_TESTS=1 to run live USGS regression",
)
def test_live_usgs_3dep_loch_vale_pipeline(tmp_path):
    pytest.importorskip("h3")
    pytest.importorskip("rasterio")
    pytest.importorskip("geopandas")

    from hydrohex.real_dem import run_usgs_real_dem_test

    # A compact Loch Vale clip keeps the live regression practical while using
    # the production 1 m / H3 res-13 settings.
    summary = run_usgs_real_dem_test(
        tmp_path,
        bbox=(-105.662, 40.288, -105.654, 40.296),
        pixel_size_m=1.0,
        h3_resolution=13,
        sampling="bilinear",
        condition="fill",
        workers=2,
        site_slug="loch_vale_test",
    )
    assert summary["status"] == "ok"
    assert summary["site"] == "loch_vale_test"
    assert summary["cells"] > 5_000
    assert summary["elevation_max_m"] > summary["elevation_min_m"]
    assert summary["d6_max_accum_area_m2"] > 0
    assert summary["dinf_max_accum_area_m2"] > 0
