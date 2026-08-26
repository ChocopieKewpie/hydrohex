from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence


def _add_input_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("input", type=Path, help="Input H3 DEM: .csv, .gpkg, .parquet/.pq, or partitioned Parquet directory")
    parser.add_argument("output", type=Path, help="Output .csv or .gpkg")
    parser.add_argument("--layer", default="cells", help="GeoPackage input layer")
    parser.add_argument("--id-field", default=None, help="H3 identifier field")
    parser.add_argument("--elevation-field", default=None, help="Elevation column; auto-detected for Parquet, otherwise elevation_m")


def _add_preprocess_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--smooth",
        choices=["none", "mean", "median", "bilateral"],
        default="none",
        help="Optional smoothing before hydrologic conditioning",
    )
    parser.add_argument("--smooth-iterations", type=int, default=1)
    parser.add_argument("--spatial-sigma-m", type=float, default=30.0)
    parser.add_argument("--elevation-sigma-m", type=float, default=5.0)
    parser.add_argument(
        "--condition",
        choices=["none", "fill", "breach", "hybrid"],
        default="none",
    )
    parser.add_argument("--min-slope", type=float, default=1e-5)
    parser.add_argument("--max-fill-depth-m", type=float, default=2.0)
    parser.add_argument("--max-breach-depth-m", type=float, default=20.0)
    parser.add_argument("--max-search-cells", type=int, default=100_000)


def _add_workers(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Worker threads for routing, smoothing, and wide accumulation fronts; 0 uses all logical CPUs",
    )


def _add_progress(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--no-progress",
        action="store_false",
        dest="progress",
        default=True,
        help="Disable CLI progress bars",
    )


def _add_backend(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--backend",
        choices=["auto", "indexed", "python"],
        default="auto",
        help="Routing backend; auto uses the indexed NumPy D6 kernel when available",
    )


def _methods(value: str) -> tuple[str, ...]:
    if value == "both":
        return ("d6", "dinf")
    return (value,)


def _preprocess_only(args: argparse.Namespace) -> int:
    from .h3_grid import distance_m, neighbors
    from .io import read_dem, write_dem_csv
    from .qgis import export_dem_geopackage
    from .progress import progress_bar
    from .terrain import condition_dem, smooth_dem

    raw = read_dem(
        args.input,
        layer=args.layer,
        id_field=args.id_field,
        elevation_field=args.elevation_field,
    )
    current = dict(raw)
    extra: dict[str, dict[str, object]] = {
        "elevation_raw_m": {c: float(z) for c, z in raw.items()}
    }
    if args.smooth != "none":
        smoothed = smooth_dem(
            current,
            neighbors,
            method=args.smooth,
            distance=distance_m,
            spatial_sigma=args.spatial_sigma_m,
            elevation_sigma=args.elevation_sigma_m,
            iterations=args.smooth_iterations,
            workers=args.workers,
            progress=args.progress,
        )
        current = dict(smoothed.elevation)
        extra["smooth_delta_m"] = dict(smoothed.delta)
    if args.condition != "none":
        conditioned = condition_dem(
            current,
            neighbors,
            method=args.condition,
            distance=distance_m,
            min_slope=args.min_slope,
            max_fill_depth_m=args.max_fill_depth_m,
            max_breach_depth_m=args.max_breach_depth_m,
            max_search_cells=args.max_search_cells,
            progress=args.progress,
        )
        current = dict(conditioned.elevation)
        for name, values in conditioned.diagnostics.items():
            extra[name] = dict(values)
    extra["elevation_delta_m"] = {c: current[c] - raw[c] for c in raw}
    extra["terrain_modified"] = {c: abs(current[c] - raw[c]) > 1e-12 for c in raw}

    if args.output.suffix.lower() == ".csv":
        write_dem_csv(args.output, current)
    elif args.output.suffix.lower() == ".gpkg":
        with progress_bar(total=1, desc="Exporting GeoPackage", enabled=args.progress, unit="file") as bar:
            export_dem_geopackage(current, args.output, extra_cell_fields=extra)
            bar.update(1)
    else:
        raise ValueError("preprocess output must be .csv or .gpkg")
    print(args.output)
    return 0


def _run_pipeline(args: argparse.Namespace, *, allow_preprocess: bool) -> int:
    from .io import read_dem
    from .pipeline import run_h3_pipeline
    from .qgis import export_flow_geopackage
    from .progress import progress_bar

    elevation = read_dem(
        args.input,
        layer=args.layer,
        id_field=args.id_field,
        elevation_field=args.elevation_field,
    )
    result = run_h3_pipeline(
        elevation,
        methods=_methods(args.method),
        smooth=args.smooth if allow_preprocess else "none",
        smooth_iterations=args.smooth_iterations if allow_preprocess else 1,
        spatial_sigma_m=args.spatial_sigma_m if allow_preprocess else 30.0,
        elevation_sigma_m=args.elevation_sigma_m if allow_preprocess else 5.0,
        condition=args.condition if allow_preprocess else "none",
        min_slope=args.min_slope if allow_preprocess else 1e-5,
        max_fill_depth_m=args.max_fill_depth_m if allow_preprocess else 2.0,
        max_breach_depth_m=args.max_breach_depth_m if allow_preprocess else 20.0,
        max_search_cells=args.max_search_cells if allow_preprocess else 100_000,
        workers=args.workers,
        backend=args.backend,
        progress=args.progress,
    )
    if args.output.suffix.lower() != ".gpkg":
        raise ValueError("route/pipeline output is currently GeoPackage (.gpkg)")
    with progress_bar(total=1, desc="Exporting GeoPackage", enabled=args.progress, unit="file") as bar:
        export_flow_geopackage(
            result.elevation,
            result.d6,
            args.output,
            dinf_results=result.dinf,
            d6_accumulation=result.d6_accumulation,
            dinf_accumulation=result.dinf_accumulation,
            extra_cell_fields=result.extra_cell_fields,
        )
        bar.update(1)
    print(args.output)
    return 0


def _fetch_dem(args: argparse.Namespace) -> int:
    from .usgs import fetch_usgs_3dep, site_bbox

    bbox = tuple(args.bbox) if args.bbox is not None else site_bbox(args.site)
    metadata = fetch_usgs_3dep(
        args.output,
        bbox=bbox,
        pixel_size_m=args.pixel_size_m,
        overwrite=args.overwrite,
        tile_size=args.tile_size,
    )
    print(args.output)
    print(json.dumps({
        "width": metadata.width,
        "height": metadata.height,
        "pixel_size_m": metadata.requested_pixel_size_m,
        "delivery_mode": metadata.delivery_mode,
        "tile_count": metadata.tile_count,
    }))
    return 0


def _import_raster(args: argparse.Namespace) -> int:
    from .io import write_dem_csv
    from .qgis import export_dem_geopackage
    from .raster import raster_to_h3

    result = raster_to_h3(
        args.input,
        resolution=args.resolution,
        sampling=args.sampling,
        band=args.band,
    )
    if args.output.suffix.lower() == ".csv":
        write_dem_csv(args.output, result.elevation)
    elif args.output.suffix.lower() == ".gpkg":
        export_dem_geopackage(result.elevation, args.output)
    else:
        raise ValueError("import-raster output must be .csv or .gpkg")
    print(args.output)
    print(json.dumps({
        "cells": len(result.elevation),
        "resolution": result.h3_resolution,
        "sampling": result.sampling,
    }))
    return 0


def _real_dem_test(args: argparse.Namespace) -> int:
    from .real_dem import run_usgs_real_dem_test

    from .usgs import site_bbox

    bbox = tuple(args.bbox) if args.bbox is not None else site_bbox(args.site)
    summary = run_usgs_real_dem_test(
        args.work_dir,
        bbox=bbox,
        pixel_size_m=args.pixel_size_m,
        h3_resolution=args.resolution,
        sampling=args.sampling,
        condition=args.condition,
        smooth=args.smooth,
        workers=args.workers,
        overwrite=args.overwrite,
        site_slug=args.site,
        tile_size=args.tile_size,
        backend=args.backend,
        progress=args.progress,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _generate(args: argparse.Namespace) -> int:
    if args.format == "gpkg":
        from .qgis_datasets import generate_qgis_suite

        outputs = generate_qgis_suite(
            args.output_dir,
            args.lat,
            args.lng,
            args.resolution,
            args.radius,
            workers=args.workers,
        )
    else:
        from .datasets import generate_suite

        outputs = generate_suite(
            args.output_dir,
            args.lat,
            args.lng,
            args.resolution,
            args.radius,
        )
    for path in outputs:
        print(path)
    return 0


def _self_test(args: argparse.Namespace) -> int:
    from .selftest import run_self_test

    summary = run_self_test(workers=args.workers, include_gis=not args.skip_gis)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _benchmark(args: argparse.Namespace) -> int:
    from .benchmark import (
        benchmark_d6_backends,
        format_benchmark,
        write_benchmark_csv,
        write_benchmark_json,
    )
    from .h3_grid import distance_m, latlng, neighbors

    if args.input is None:
        import h3

        center = h3.latlng_to_cell(args.lat, args.lng, args.resolution)
        cells = tuple(h3.grid_disk(center, args.radius))
        center_lat, center_lng = h3.cell_to_latlng(center)
        elevation = {}
        for cell in cells:
            lat, lng = h3.cell_to_latlng(cell)
            elevation[cell] = (
                2500.0
                + 5000.0 * (lat - center_lat)
                + 1500.0 * (lng - center_lng)
            )
        source = f"synthetic H3 r{args.resolution} radius {args.radius}"
    else:
        from .io import read_dem

        elevation = read_dem(
            args.input,
            layer=args.layer,
            id_field=args.id_field,
            elevation_field=args.elevation_field,
        )
        source = str(args.input)

    result = benchmark_d6_backends(
        elevation,
        neighbors,
        distance_m,
        latlng,
        workers=args.workers,
        repeats=args.repeats,
        warmup=args.warmup,
        source=source,
    )
    print(format_benchmark(result))
    if args.json_output is not None:
        write_benchmark_json(args.json_output, result)
        print(args.json_output)
    if args.csv_output is not None:
        write_benchmark_csv(args.csv_output, result)
        print(args.csv_output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hydrohex",
        description="DGGS-native terrain preprocessing, D6/D-infinity routing and flow accumulation.",
    )
    from . import __version__

    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser("generate", help="Generate deterministic analytic H3 test DEMs")
    generate.add_argument("--output-dir", type=Path, default=Path("data/generated"))
    generate.add_argument("--format", choices=["gpkg", "csv"], default="gpkg")
    generate.add_argument("--lat", type=float, default=-36.8485)
    generate.add_argument("--lng", type=float, default=174.7633)
    generate.add_argument("--resolution", type=int, default=12)
    generate.add_argument("--radius", type=int, default=None)
    _add_workers(generate)
    generate.set_defaults(handler=_generate)

    fetch_dem = sub.add_parser("fetch-dem", help="Download a clipped USGS 3DEP DEM")
    fetch_dem.add_argument("output", type=Path)
    fetch_dem.add_argument(
        "--site", choices=["loch-vale", "boulder"], default="loch-vale",
        help="Built-in AOI used when --bbox is omitted",
    )
    fetch_dem.add_argument(
        "--bbox", nargs=4, type=float, metavar=("WEST", "SOUTH", "EAST", "NORTH"),
        default=None,
        help="Optional longitude/latitude bounding box overriding --site",
    )
    fetch_dem.add_argument(
        "--pixel-size-m", type=float, default=1.0,
        help="Requested ground sampling interval; 1 m matches the highest-resolution seamless 3DEP product",
    )
    fetch_dem.add_argument("--tile-size", type=int, default=1024, help="Maximum pixels per USGS request tile")
    fetch_dem.add_argument("--overwrite", action="store_true")
    fetch_dem.set_defaults(handler=_fetch_dem)

    import_raster = sub.add_parser("import-raster", help="Sample a raster DEM onto H3 cell centres")
    import_raster.add_argument("input", type=Path)
    import_raster.add_argument("output", type=Path)
    import_raster.add_argument("--resolution", type=int, default=13)
    import_raster.add_argument("--sampling", choices=["nearest", "bilinear"], default="bilinear")
    import_raster.add_argument("--band", type=int, default=1)
    import_raster.set_defaults(handler=_import_raster)

    real_dem = sub.add_parser(
        "real-dem-test",
        help="Fetch USGS 3DEP, ingest to H3, route, accumulate and export a QGIS benchmark",
    )
    real_dem.add_argument("--work-dir", type=Path, default=Path("data/real_dem/loch_vale"))
    real_dem.add_argument(
        "--site", choices=["loch-vale", "boulder"], default="loch-vale",
        help="Built-in real-terrain benchmark site used when --bbox is omitted",
    )
    real_dem.add_argument(
        "--bbox", nargs=4, type=float, metavar=("WEST", "SOUTH", "EAST", "NORTH"),
        default=None,
        help="Optional longitude/latitude bounding box overriding --site",
    )
    real_dem.add_argument("--pixel-size-m", type=float, default=1.0)
    real_dem.add_argument("--resolution", type=int, default=13)
    real_dem.add_argument("--sampling", choices=["nearest", "bilinear"], default="bilinear")
    real_dem.add_argument("--smooth", choices=["none", "mean", "median", "bilateral"], default="none")
    real_dem.add_argument("--condition", choices=["none", "fill", "breach", "hybrid"], default="fill")
    real_dem.add_argument("--tile-size", type=int, default=1024, help="Maximum pixels per USGS request tile")
    real_dem.add_argument("--overwrite", action="store_true")
    _add_workers(real_dem)
    _add_backend(real_dem)
    _add_progress(real_dem)
    real_dem.set_defaults(handler=_real_dem_test)

    preprocess = sub.add_parser("preprocess", help="Smooth and/or hydrologically condition a DEM")
    _add_input_args(preprocess)
    _add_preprocess_args(preprocess)
    _add_workers(preprocess)
    _add_progress(preprocess)
    preprocess.set_defaults(handler=_preprocess_only)

    route = sub.add_parser("route", help="Run D6/D-infinity routing and accumulation")
    _add_input_args(route)
    route.add_argument("--method", choices=["d6", "dinf", "both"], default="both")
    _add_workers(route)
    _add_backend(route)
    _add_progress(route)
    route.set_defaults(handler=lambda a: _run_pipeline(a, allow_preprocess=False))

    pipeline = sub.add_parser(
        "pipeline", help="Preprocess, route, accumulate and export one H3 DEM"
    )
    _add_input_args(pipeline)
    pipeline.add_argument("--method", choices=["d6", "dinf", "both"], default="both")
    _add_preprocess_args(pipeline)
    _add_workers(pipeline)
    _add_backend(pipeline)
    _add_progress(pipeline)
    pipeline.set_defaults(handler=lambda a: _run_pipeline(a, allow_preprocess=True))

    self_test = sub.add_parser("self-test", help="Run a small end-to-end toolbox verification")
    _add_workers(self_test)
    self_test.add_argument("--skip-gis", action="store_true")
    self_test.set_defaults(handler=_self_test)

    benchmark = sub.add_parser(
        "benchmark",
        help="Compare legacy Python and indexed NumPy D6 routing backends",
    )
    benchmark.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=None,
        help="Optional H3 DEM input; omit to use a generated synthetic H3 grid",
    )
    benchmark.add_argument("--layer", default="cells", help="GeoPackage input layer")
    benchmark.add_argument("--id-field", default=None, help="H3 identifier field")
    benchmark.add_argument("--elevation-field", default=None, help="Elevation field")
    benchmark.add_argument("--lat", type=float, default=-39.296)
    benchmark.add_argument("--lng", type=float, default=174.064)
    benchmark.add_argument("--resolution", type=int, default=10)
    benchmark.add_argument("--radius", type=int, default=30)
    benchmark.add_argument("--repeats", type=int, default=3)
    benchmark.add_argument("--warmup", type=int, default=1)
    benchmark.add_argument("--json", dest="json_output", type=Path, default=None)
    benchmark.add_argument("--csv", dest="csv_output", type=Path, default=None)
    _add_workers(benchmark)
    benchmark.set_defaults(handler=_benchmark)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (ValueError, ImportError, OSError, RuntimeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
