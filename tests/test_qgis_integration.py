from pathlib import Path

import pytest

h3 = pytest.importorskip("h3")
gpd = pytest.importorskip("geopandas")
pytest.importorskip("pyogrio")

from hydrohex.core import compute_flow_directions
from hydrohex.datasets import make_bowl
from hydrohex.h3_grid import distance_m, neighbors
from hydrohex.qgis import export_flow_geopackage


def test_export_geopackage_has_expected_layers(tmp_path: Path):
    center = h3.latlng_to_cell(-36.8485, 174.7633, 12)
    cells = sorted(h3.grid_disk(center, 2))
    elevation = make_bowl(cells, center)
    flow = compute_flow_directions(elevation, neighbors, distance_m)

    path = export_flow_geopackage(elevation, flow, tmp_path / "bowl.gpkg")

    assert path.exists()
    assert {"cells", "cell_centres", "flow_direction", "sinks"}.issubset(set(gpd.list_layers(path)["name"]))

    centres_layer = gpd.read_file(path, layer="cell_centres")
    assert len(centres_layer) == len(elevation)
    assert centres_layer.geometry.geom_type.eq("Point").all()

    cell_layer = gpd.read_file(path, layer="cells")
    assert len(cell_layer) == len(elevation)
    assert cell_layer.crs.to_epsg() == 4326
    assert {"h3_id", "elevation_m", "flow_to", "slope", "sink"}.issubset(cell_layer.columns)
