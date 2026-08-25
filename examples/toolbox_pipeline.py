"""Small API example: bilateral smoothing -> hybrid conditioning -> D6/Dinf -> QGIS."""

from pathlib import Path

import h3

from hydrohex.datasets import make_neutral
from hydrohex.pipeline import run_h3_pipeline
from hydrohex.qgis import export_flow_geopackage

center = h3.latlng_to_cell(-36.8485, 174.7633, 10)
cells = sorted(h3.grid_disk(center, 8))
elevation = make_neutral(
    cells,
    center,
    seed=42,
    relief_m=150.0,
    correlation_length_m=800.0,
)

result = run_h3_pipeline(
    elevation,
    smooth="bilateral",
    spatial_sigma_m=100.0,
    elevation_sigma_m=10.0,
    condition="hybrid",
    max_fill_depth_m=1.0,
    max_breach_depth_m=10.0,
    methods=("d6", "dinf"),
    workers=4,
)

path = export_flow_geopackage(
    result.elevation,
    result.d6,
    Path("data/generated/toolbox_example.gpkg"),
    dinf_results=result.dinf,
    d6_accumulation=result.d6_accumulation,
    dinf_accumulation=result.dinf_accumulation,
    extra_cell_fields=result.extra_cell_fields,
)
print(path)
