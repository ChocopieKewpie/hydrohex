from __future__ import annotations

import tempfile
from pathlib import Path


def run_self_test(*, workers: int = 2, include_gis: bool = True) -> dict[str, object]:
    """Exercise the toolbox end-to-end on a tiny deterministic H3 DEM."""
    import h3

    from .datasets import make_plane
    from .h3_grid import distance_m, neighbors
    from .pipeline import run_h3_pipeline
    from .terrain import breach_depressions, condition_dem, find_pits, priority_flood_fill, smooth_dem

    center = h3.latlng_to_cell(-36.8485, 174.7633, 9)
    cells = sorted(h3.grid_disk(center, 3))
    dem = make_plane(cells, center, z0=500.0)
    # Add deterministic local terrain irregularities so preprocessing paths are exercised.
    dem[center] -= 35.0
    ring = sorted(h3.grid_ring(center, 1))
    if ring:
        dem[ring[0]] += 12.0
        dem[ring[len(ring) // 2]] -= 8.0

    smoothed = smooth_dem(
        dem,
        neighbors,
        method="bilateral",
        distance=distance_m,
        spatial_sigma=250.0,
        elevation_sigma=20.0,
        workers=workers,
    )
    pits_before = find_pits(smoothed.elevation, neighbors)
    filled = priority_flood_fill(smoothed.elevation, neighbors, distance=distance_m)
    breached = breach_depressions(
        smoothed.elevation,
        neighbors,
        distance=distance_m,
        max_breach_depth_m=100.0,
        max_search_cells=5_000,
    )
    hybrid = condition_dem(
        smoothed.elevation,
        neighbors,
        method="hybrid",
        distance=distance_m,
        max_fill_depth_m=1.0,
        max_breach_depth_m=100.0,
        max_search_cells=5_000,
    )

    # Exercise the wide-front parallel accumulator explicitly; the tiny H3
    # self-test grid may be below the production parallel-front threshold.
    from .accumulation import accumulate
    from .graph import FlowEdge, WeightedFlowGraph

    parallel_sources = tuple(f"p{i}" for i in range(300))
    parallel_sink = "parallel_sink"
    parallel_graph = WeightedFlowGraph.from_edges(
        (*parallel_sources, parallel_sink),
        [FlowEdge(source, parallel_sink, 1.0) for source in parallel_sources],
    )
    parallel_accum = accumulate(
        parallel_graph,
        workers=workers,
        parallel_min_front_size=32,
    )
    assert parallel_accum[parallel_sink] == 301.0
    if workers != 1 and parallel_accum.stats is not None:
        assert parallel_accum.stats.parallel_fronts >= 1

    result = run_h3_pipeline(
        dem,
        methods=("d6", "dinf"),
        smooth="bilateral",
        spatial_sigma_m=250.0,
        elevation_sigma_m=20.0,
        condition="hybrid",
        max_fill_depth_m=1.0,
        max_breach_depth_m=100.0,
        max_search_cells=5_000,
        workers=workers,
    )
    assert result.d6 is not None and result.dinf is not None
    assert result.d6_accumulation is not None and result.dinf_accumulation is not None
    assert len(result.d6) == len(cells) == len(result.dinf)

    output: str | None = None
    if include_gis:
        from .qgis import export_flow_geopackage

        with tempfile.TemporaryDirectory(prefix="hydrohex-selftest-") as td:
            path = export_flow_geopackage(
                result.elevation,
                result.d6,
                Path(td) / "selftest.gpkg",
                dinf_results=result.dinf,
                d6_accumulation=result.d6_accumulation,
                dinf_accumulation=result.dinf_accumulation,
                extra_cell_fields=result.extra_cell_fields,
            )
            if not path.exists() or path.stat().st_size == 0:
                raise AssertionError("GeoPackage self-test export failed")
            output = "GeoPackage write verified"

    return {
        "cells": len(cells),
        "pits_before_conditioning": len(pits_before),
        "smoothed_modified_cells": len(smoothed.modified_cells),
        "filled_modified_cells": len(filled.modified_cells),
        "breached_modified_cells": len(breached.modified_cells),
        "hybrid_modified_cells": len(hybrid.modified_cells),
        "d6_sinks": sum(r.flow_to is None for r in result.d6.values()),
        "dinf_sinks": sum(r.sink for r in result.dinf.values()),
        "accumulation_parallel_fronts": (
            parallel_accum.stats.parallel_fronts if parallel_accum.stats is not None else 0
        ),
        "gis": output if include_gis else "skipped",
        "status": "ok",
    }
