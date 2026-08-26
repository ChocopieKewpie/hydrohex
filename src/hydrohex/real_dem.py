from __future__ import annotations

import json
from pathlib import Path

from .raster import raster_to_h3
from .usgs import DEFAULT_LOCH_VALE_BBOX, DEFAULT_PIXEL_SIZE_M, fetch_usgs_3dep


def _safe_slug(value: str) -> str:
    return "_".join(part for part in value.lower().replace("-", "_").split("_") if part)


def _pixel_slug(pixel_size_m: float) -> str:
    value = float(pixel_size_m)
    if value.is_integer():
        return f"{int(value)}m"
    return f"{value:g}".replace(".", "p") + "m"


def run_usgs_real_dem_test(
    work_dir: str | Path,
    *,
    bbox: tuple[float, float, float, float] = DEFAULT_LOCH_VALE_BBOX,
    pixel_size_m: float = DEFAULT_PIXEL_SIZE_M,
    h3_resolution: int = 13,
    sampling: str = "bilinear",
    condition: str = "fill",
    smooth: str = "none",
    workers: int = 1,
    overwrite: bool = False,
    site_slug: str = "loch_vale",
    tile_size: int = 1024,
    backend: str = "auto",
    progress: bool = False,
) -> dict[str, object]:
    """Fetch a real 3DEP DEM, ingest it to H3, route it, accumulate it and export QGIS output."""
    from .io import write_dem_csv
    from .pipeline import run_h3_pipeline
    from .qgis import export_dem_geopackage, export_flow_geopackage

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    slug = _safe_slug(site_slug)
    pixel_slug = _pixel_slug(pixel_size_m)
    raster_path = work_dir / f"usgs_3dep_{slug}_{pixel_slug}.tif"
    raster_sidecar = raster_path.with_suffix(raster_path.suffix + ".json")
    completed_download = raster_path.exists() and raster_sidecar.exists()
    if not completed_download or overwrite:
        fetch_meta = fetch_usgs_3dep(
            raster_path,
            bbox=bbox,
            pixel_size_m=pixel_size_m,
            overwrite=(overwrite or raster_path.exists()),
            tile_size=tile_size,
        )
    else:
        # Keep the existing raster but rebuild deterministic request metadata for reporting.
        from .usgs import build_usgs_3dep_export_url

        _, fetch_meta = build_usgs_3dep_export_url(bbox, pixel_size_m=pixel_size_m)

    imported = raster_to_h3(
        raster_path,
        resolution=h3_resolution,
        sampling=sampling,
    )
    h3_csv = write_dem_csv(work_dir / f"{slug}_h3_r{h3_resolution}.csv", imported.elevation)
    h3_gpkg = export_dem_geopackage(
        imported.elevation,
        work_dir / f"{slug}_h3_r{h3_resolution}.gpkg",
    )

    result = run_h3_pipeline(
        imported.elevation,
        methods=("d6", "dinf"),
        smooth=smooth,
        condition=condition,
        workers=workers,
        backend=backend,
        progress=progress,
    )
    flow_gpkg = export_flow_geopackage(
        result.elevation,
        result.d6,
        work_dir / f"{slug}_h3_r{h3_resolution}_flow.gpkg",
        dinf_results=result.dinf,
        d6_accumulation=result.d6_accumulation,
        dinf_accumulation=result.dinf_accumulation,
        extra_cell_fields=result.extra_cell_fields,
    )

    d6_max = max(result.d6_accumulation.area_m2.values.values()) if result.d6_accumulation else None
    dinf_max = (
        max(result.dinf_accumulation.area_m2.values.values()) if result.dinf_accumulation else None
    )
    summary: dict[str, object] = {
        "status": "ok",
        "site": slug,
        "source": fetch_meta.source,
        "source_url": fetch_meta.url,
        "bbox": list(bbox),
        "requested_pixel_size_m": pixel_size_m,
        "pixel_size_m": pixel_size_m,  # backward-compatible summary key
        "download_delivery_mode": fetch_meta.delivery_mode,
        "download_tile_count": fetch_meta.tile_count,
        "download_tile_size": tile_size,
        "h3_resolution": h3_resolution,
        "sampling": sampling,
        "condition": condition,
        "smooth": smooth,
        "backend": result.backend,
        "cells": len(imported.elevation),
        "elevation_min_m": min(imported.elevation.values()),
        "elevation_max_m": max(imported.elevation.values()),
        "d6_sinks": sum(r.flow_to is None for r in result.d6.values()) if result.d6 else None,
        "dinf_sinks": sum(r.sink for r in result.dinf.values()) if result.dinf else None,
        "d6_max_accum_area_m2": d6_max,
        "dinf_max_accum_area_m2": dinf_max,
        "raster": str(raster_path),
        "h3_csv": str(h3_csv),
        "h3_gpkg": str(h3_gpkg),
        "flow_gpkg": str(flow_gpkg),
    }
    (work_dir / "real_dem_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
