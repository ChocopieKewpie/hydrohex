# Changelog

## 0.2.0 - Indexed routing benchmarks and performance tooling

- Added `hydrohex benchmark` to compare the legacy Python D6 implementation against the indexed NumPy backend on either a real input DEM or a generated H3 grid.
- Benchmark output reports legacy routing time, indexed topology-build time, reusable indexed routing time, first-run cost, routing-only speedup, first-run speedup, and exact receiver equivalence.
- Added optional JSON and CSV benchmark exports for repeatable performance tracking.
- Retained `--backend python` as the correctness/performance reference while `--backend auto` continues to prefer the indexed D6 backend.
- Added benchmark regression tests and CLI coverage.

## 0.1.0 - Initial release

- Introduced **HydroHex**, a DGGS-native hydrology toolbox with H3 as the first backend.
- Added D6 and facet-based D∞ flow direction.
- Added an indexed NumPy D6 backend with `N × 6` neighbor indices, vectorized H3 center distances, chunked worker execution, and a retained Python reference backend.
- Added CLI progress bars for topology construction, smoothing/conditioning, D6/D∞ routing, accumulation fronts, and export stages, with `--no-progress` for quiet runs.
- Added weighted flow graphs and serial/parallel topological-front flow accumulation.
- Added DEM preprocessing: mean/median/bilateral smoothing, pit/flat diagnostics, Priority-Flood filling, breaching, and hybrid conditioning.
- Added QGIS-ready GeoPackage outputs with cell polygons, cell centres, routing vectors, sinks, accumulation, and conditioning diagnostics.
- Added raster-to-H3 ingestion and a USGS 3DEP Loch Vale real-DEM benchmark workflow.
- Added direct Parquet/GeoParquet ingestion, including Hive-partitioned `raster2dggs` H3 datasets with automatic target H3/elevation field detection.
- Added robust tiled 3DEP downloads with retry handling and seam-safe raster mosaicking.
- Added the `hydrohex` CLI, Conda environment, CI tests, examples, documentation, logo, and benchmark screenshot.
