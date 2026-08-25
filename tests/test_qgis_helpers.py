import pytest

pytest.importorskip("geopandas")
pytest.importorskip("shapely")

from hydrohex.qgis import _polygon_from_latlng_boundary


def test_h3_latlng_boundary_is_converted_to_xy_polygon():
    polygon = _polygon_from_latlng_boundary(
        [
            (-36.0, 174.0),
            (-36.0, 175.0),
            (-37.0, 175.0),
            (-37.0, 174.0),
        ]
    )
    assert polygon.is_valid
    assert polygon.bounds == pytest.approx((174.0, -37.0, 175.0, -36.0))


def test_geopackage_export_writes_three_layers_without_h3_runtime(tmp_path, monkeypatch):
    import geopandas as gpd

    from hydrohex.core import FlowResult
    from hydrohex.dinf import DInfFlowResult
    import hydrohex.qgis as qgis

    class FakeH3:
        boundaries = {
            "a": [(0.0, 0.0), (0.0, 0.01), (0.01, 0.01), (0.01, 0.0)],
            "b": [(0.01, 0.0), (0.01, 0.01), (0.02, 0.01), (0.02, 0.0)],
        }
        centers = {"a": (0.005, 0.005), "b": (0.015, 0.005)}

        @classmethod
        def cell_to_boundary(cls, cell):
            return cls.boundaries[cell]

        @classmethod
        def cell_to_latlng(cls, cell):
            return cls.centers[cell]

        @staticmethod
        def great_circle_distance(a, b, unit="m"):
            # Sufficient deterministic distance for display-vector tests.
            import math
            return math.hypot(a[0] - b[0], a[1] - b[1]) * 111_000.0

    monkeypatch.setattr(qgis, "_h3_import", lambda: FakeH3)

    elevation = {"a": 10.0, "b": 5.0}
    flow = {
        "a": FlowResult("a", "b", 5.0, 1000.0, 0.005),
        "b": FlowResult("b", None, 0.0, 0.0, 0.0),
    }

    dinf = {
        "a": DInfFlowResult("a", 1.5707963267948966, 0.005, "b", 1.0, None, 0.0),
        "b": DInfFlowResult("b", None, 0.0, None, 0.0, None, 0.0),
    }

    from hydrohex.accumulation import accumulate_flow
    from hydrohex.graph import graph_from_d6, graph_from_dinf

    areas = {"a": 100.0, "b": 100.0}
    d6_accum = accumulate_flow(graph_from_d6(flow), areas, edge_contaminated_sources={"a"})
    dinf_accum = accumulate_flow(
        graph_from_dinf(dinf), areas, edge_contaminated_sources={"a"}
    )

    path = qgis.export_flow_geopackage(
        elevation,
        flow,
        tmp_path / "test.gpkg",
        dinf_results=dinf,
        d6_accumulation=d6_accum,
        dinf_accumulation=dinf_accum,
    )
    layers = set(gpd.list_layers(path)["name"])
    assert layers == {
        "cells", "cell_centres", "flow_direction", "sinks",
        "dinf_cells", "dinf_direction", "dinf_receivers", "dinf_sinks",
    }
    assert len(gpd.read_file(path, layer="cells")) == 2
    centres = gpd.read_file(path, layer="cell_centres")
    assert len(centres) == 2
    assert centres.geometry.geom_type.eq("Point").all()
    assert {
        "d6_flow_to", "d6_slope", "d6_dir_deg_n_cw",
        "dinf_dir_rad", "dinf_dir_deg_e_ccw", "dinf_dir_deg_n_cw",
        "d6_accum_cells", "d6_accum_area_m2", "d6_edge_contam",
        "dinf_accum_cells", "dinf_accum_area_m2", "dinf_edge_contam",
    }.issubset(centres.columns)
    a = centres.set_index("h3_id").loc["a"]
    assert a["d6_dir_deg_n_cw"] == pytest.approx(0.0)
    assert a["dinf_dir_deg_n_cw"] == pytest.approx(0.0)
    assert a["d6_accum_area_m2"] == pytest.approx(100.0)
    assert a["dinf_accum_area_m2"] == pytest.approx(100.0)
    assert bool(a["d6_edge_contam"]) is True
    assert bool(a["dinf_edge_contam"]) is True
    b = centres.set_index("h3_id").loc["b"]
    assert b["d6_accum_area_m2"] == pytest.approx(200.0)
    assert b["dinf_accum_area_m2"] == pytest.approx(200.0)
    assert len(gpd.read_file(path, layer="flow_direction")) == 1
    assert len(gpd.read_file(path, layer="sinks")) == 1
    assert len(gpd.read_file(path, layer="dinf_cells")) == 2
    assert len(gpd.read_file(path, layer="dinf_direction")) == 1
    assert len(gpd.read_file(path, layer="dinf_receivers")) == 1
    assert len(gpd.read_file(path, layer="dinf_sinks")) == 1
