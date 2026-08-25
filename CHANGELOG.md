# Changelog

## 0.1.0 - Initial release

- Introduced **HydroHex**, a DGGS-native hydrology toolbox with H3 as the first backend.
- Added D6 and facet-based D∞ flow direction.
- Added weighted flow graphs and serial/parallel topological-front flow accumulation.
- Added DEM preprocessing: mean/median/bilateral smoothing, pit/flat diagnostics, Priority-Flood filling, breaching, and hybrid conditioning.
- Added QGIS-ready GeoPackage outputs with cell polygons, cell centres, routing vectors, sinks, accumulation, and conditioning diagnostics.
- Added raster-to-H3 ingestion and a USGS 3DEP Loch Vale real-DEM benchmark workflow.
- Added direct Parquet/GeoParquet ingestion, including Hive-partitioned `raster2dggs` H3 datasets with automatic target H3/elevation field detection.
- Added robust tiled 3DEP downloads with retry handling and seam-safe raster mosaicking.
- Added the `hydrohex` CLI, Conda environment, CI tests, examples, documentation, logo, and benchmark screenshot.
