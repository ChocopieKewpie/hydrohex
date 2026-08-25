from pathlib import Path

import h3

from hydrohex.core import compute_flow_directions
from hydrohex.datasets import make_plane
from hydrohex.dinf import compute_dinf_flow_directions
from hydrohex.h3_grid import distance_m, local_xy_m, neighbors
from hydrohex.qgis import export_flow_geopackage

center = h3.latlng_to_cell(-36.8485, 174.7633, 12)
cells = sorted(h3.grid_disk(center, 4))
elevation = make_plane(cells, center)

d6 = compute_flow_directions(elevation, neighbors, distance_m)
dinf = compute_dinf_flow_directions(elevation, neighbors, local_xy_m)

path = export_flow_geopackage(
    elevation,
    d6,
    Path("data/generated/example_plane.gpkg"),
    dinf_results=dinf,
)
print(path)
