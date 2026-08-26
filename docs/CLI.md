# CLI reference

The installed entry point is:

```bash
hydrohex --help
```

## `generate`

Generate deterministic analytic CSV or QGIS GeoPackage benchmark suites.

```bash
hydrohex generate --format gpkg --output-dir data/generated --workers 4
```

Use `--resolution` and `--radius` to control the grid. If radius is omitted, the generator scales the original res-8/radius-4 footprint to the requested resolution.

## `fetch-dem`

Download a clipped float32 GeoTIFF from the public USGS 3DEP dynamic elevation ImageServer.

```bash
hydrohex fetch-dem data/real_dem/loch_vale/usgs_3dep_loch_vale_1m.tif \
  --site loch-vale \
  --pixel-size-m 1
```

The default site is Loch Vale, Colorado. `--site boulder` remains available, and a custom `--bbox WEST SOUTH EAST NORTH` overrides the site. Output dimensions are derived from great-circle width/height so `--pixel-size-m` approximates the requested ground sampling interval while the GeoTIFF remains in geographic coordinates. The 1 m default matches the highest-resolution seamless 3DEP product; because the ImageServer is a dynamic multi-resolution mosaic, source resolution can vary. A JSON sidecar records the requested bounding box, dimensions and source URL.

## `import-raster`

Sample any GDAL/rasterio-readable DEM onto H3 cell centres.

```bash
hydrohex import-raster dem.tif dem_h3.gpkg \
  --resolution 13 \
  --sampling bilinear
```

Supported sampling methods are `nearest` and `bilinear`. Output can be `.csv` or `.gpkg`.

## `real-dem-test`

Run the complete realism benchmark: fetch 3DEP, ingest to H3, condition, compute D6/D∞, accumulate, and export QGIS layers.

```bash
hydrohex real-dem-test --site loch-vale --work-dir data/real_dem/loch_vale --workers 8
```

Defaults use the Loch Vale watershed AOI, a 1 m requested 3DEP sampling interval and H3 resolution 13.

## `preprocess`

```bash
hydrohex preprocess INPUT OUTPUT [smoothing options] [conditioning options]
```

Input: `.csv` or `.gpkg`. Output: `.csv` or `.gpkg`.

For GeoPackage input the default layer is `cells`; override with `--layer`. The default ID/elevation fields are `h3_id` and `elevation_m` (CSV also auto-detects `h3_cell`).

## `route`

```bash
hydrohex route INPUT OUTPUT --method d6|dinf|both --workers N
```

Output is a GeoPackage containing flow/accumulation layers. `--workers` is used by indexed D6 chunks, D∞ routing, and sufficiently wide topological accumulation fronts. `--backend auto` (default) selects indexed NumPy D6; `--backend python` retains the reference implementation. Progress bars are enabled by default and can be disabled with `--no-progress`.

## `pipeline`

`pipeline` combines preprocessing and routing in one reproducible command.

```bash
hydrohex pipeline INPUT OUTPUT \
  --smooth bilateral \
  --condition hybrid \
  --method both \
  --workers 8
```

## `self-test`

```bash
hydrohex self-test --workers 2
```

This creates a small deterministic H3 terrain in memory and exercises smoothing, pit detection, fill, breach, hybrid conditioning, D6, D∞, weighted graphs, accumulation, and GeoPackage output. Use `--skip-gis` to omit the final GeoPackage write.

For the live real-terrain regression test:

```bash
DGGS_FLOW_RUN_NETWORK_TESTS=1 pytest tests/test_real_dem.py -q
```

## Parquet / raster2dggs input

`preprocess`, `route`, and `pipeline` accept `.parquet`, `.pq`, `.geoparquet`, and Hive-partitioned Parquet dataset directories directly. For standard `raster2dggs h3` output, HydroHex auto-detects the finest `h3_XX` field as the routing cell ID and prefers scalar `band_1` as elevation. Use `--id-field` and `--elevation-field` to override detection.

```powershell
hydrohex pipeline Taranaki_h3 Taranaki_flow.gpkg --method both --condition fill --workers 8
```

## Processing progress and backend selection

`route`, `pipeline`, `preprocess`, and `real-dem-test` show progress by default for long-running stages. Use `--no-progress` for quiet batch execution.

D6 supports `--backend auto|indexed|python`. `auto` is the default and selects the indexed NumPy implementation. The Python backend is retained as a reference for numerical comparisons.

```powershell
hydrohex pipeline Taranaki_h3.gpkg Taranaki_flow.gpkg --method both --condition fill --backend auto --workers 8
```

## Benchmark D6 backends

Compare the legacy Python D6 implementation with the indexed NumPy backend on an existing DEM:

```powershell
hydrohex benchmark Taranaki_h3.gpkg --layer cells --id-field h3_13 --elevation-field band_1 --workers 8 --repeats 3 --json Taranaki_benchmark.json --csv Taranaki_benchmark.csv
```

Or use the built-in deterministic H3 benchmark grid:

```powershell
hydrohex benchmark --resolution 10 --radius 30 --workers 8 --repeats 3
```

The benchmark reports routing-only speedup as well as the first-run speedup including indexed topology construction. Receiver equivalence is checked exactly before results are accepted.
