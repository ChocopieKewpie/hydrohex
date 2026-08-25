from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .accumulation import FlowAccumulation, accumulate_flow, boundary_cells
from .core import FlowResult, compute_flow_directions
from .dinf import DInfFlowResult, compute_dinf_flow_directions
from .graph import graph_from_d6, graph_from_dinf
from .h3_grid import cell_area_m2, distance_m, local_xy_m, neighbors
from .terrain import TerrainResult, condition_dem, smooth_dem


@dataclass(frozen=True, slots=True)
class H3PipelineResult:
    raw_elevation: Mapping[str, float]
    elevation: Mapping[str, float]
    smoothing: TerrainResult | None
    conditioning: TerrainResult | None
    d6: Mapping[str, FlowResult] | None
    dinf: Mapping[str, DInfFlowResult] | None
    d6_accumulation: FlowAccumulation | None
    dinf_accumulation: FlowAccumulation | None
    extra_cell_fields: Mapping[str, Mapping[str, object]]


def _preprocessing_fields(
    raw: Mapping[str, float],
    current: Mapping[str, float],
    smoothing: TerrainResult | None,
    conditioning: TerrainResult | None,
) -> dict[str, Mapping[str, object]]:
    fields: dict[str, Mapping[str, object]] = {
        "elevation_raw_m": {cell: float(raw[cell]) for cell in raw},
        "elevation_delta_m": {cell: float(current[cell]) - float(raw[cell]) for cell in raw},
        "terrain_modified": {
            cell: abs(float(current[cell]) - float(raw[cell])) > 1e-12 for cell in raw
        },
    }
    if smoothing is not None:
        fields["smooth_delta_m"] = smoothing.delta
    if conditioning is not None:
        for name, values in conditioning.diagnostics.items():
            fields[name] = values
    return fields


def run_h3_pipeline(
    elevation: Mapping[str, float],
    *,
    methods: tuple[str, ...] = ("d6", "dinf"),
    smooth: str = "none",
    smooth_iterations: int = 1,
    spatial_sigma_m: float = 30.0,
    elevation_sigma_m: float = 5.0,
    condition: str = "none",
    min_slope: float = 1e-5,
    max_fill_depth_m: float = 2.0,
    max_breach_depth_m: float | None = 20.0,
    max_search_cells: int = 100_000,
    workers: int = 1,
) -> H3PipelineResult:
    """Run optional preprocessing, routing, and accumulation on an H3 DEM."""
    requested = tuple(dict.fromkeys(m.lower() for m in methods))
    unknown = set(requested).difference({"d6", "dinf"})
    if unknown:
        raise ValueError(f"Unknown routing method(s): {sorted(unknown)}")
    if not requested:
        raise ValueError("At least one routing method is required")

    raw = {cell: float(z) for cell, z in elevation.items()}
    current = dict(raw)
    smoothing: TerrainResult | None = None
    conditioning: TerrainResult | None = None

    smooth = smooth.lower()
    if smooth != "none":
        smoothing = smooth_dem(
            current,
            neighbors,
            method=smooth,
            distance=distance_m,
            spatial_sigma=spatial_sigma_m,
            elevation_sigma=elevation_sigma_m,
            iterations=smooth_iterations,
            workers=workers,
        )
        current = dict(smoothing.elevation)

    condition = condition.lower()
    if condition != "none":
        conditioning = condition_dem(
            current,
            neighbors,
            method=condition,
            distance=distance_m,
            min_slope=min_slope,
            max_fill_depth_m=max_fill_depth_m,
            max_breach_depth_m=max_breach_depth_m,
            max_search_cells=max_search_cells,
        )
        current = dict(conditioning.elevation)

    contaminated_sources = boundary_cells(set(current), neighbors)
    areas = {cell: cell_area_m2(cell) for cell in current}

    d6 = None
    dinf = None
    d6_accum = None
    dinf_accum = None
    if "d6" in requested:
        d6 = compute_flow_directions(
            current, neighbors, distance_m, workers=workers
        )
        d6_accum = accumulate_flow(
            graph_from_d6(d6),
            areas,
            edge_contaminated_sources=contaminated_sources,
            workers=workers,
        )
    if "dinf" in requested:
        dinf = compute_dinf_flow_directions(
            current, neighbors, local_xy_m, workers=workers
        )
        dinf_accum = accumulate_flow(
            graph_from_dinf(dinf),
            areas,
            edge_contaminated_sources=contaminated_sources,
            workers=workers,
        )

    return H3PipelineResult(
        raw_elevation=raw,
        elevation=current,
        smoothing=smoothing,
        conditioning=conditioning,
        d6=d6,
        dinf=dinf,
        d6_accumulation=d6_accum,
        dinf_accumulation=dinf_accum,
        extra_cell_fields=_preprocessing_fields(raw, current, smoothing, conditioning),
    )
