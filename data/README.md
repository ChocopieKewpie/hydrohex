# Data

`data/generated/` contains deterministic analytic H3 DEMs generated locally and is not committed.

```bash
hydrohex generate --format gpkg --output-dir data/generated
```

The default analytic benchmark uses H3 resolution 12 and a footprint-scaled radius of 220.

`data/real_dem/` is the preferred realism benchmark. It is populated on demand from USGS 3DEP:

```bash
hydrohex real-dem-test --site loch-vale --work-dir data/real_dem/loch_vale --workers 4
```

The real-terrain defaults are a 1 m requested USGS 3DEP export over Loch Vale and H3 resolution 13. Downloaded rasters and derived GeoPackages are intentionally not committed.
