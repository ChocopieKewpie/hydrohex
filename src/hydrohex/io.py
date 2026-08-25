from __future__ import annotations

import csv
from pathlib import Path
from typing import Mapping


def read_dem_csv(
    path: str | Path,
    *,
    id_field: str | None = None,
    elevation_field: str = "elevation_m",
) -> dict[str, float]:
    """Read an H3 DEM CSV.

    The identifier field defaults to ``h3_cell`` when present, otherwise ``h3_id``.
    """
    with Path(path).open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSV has no header")
        resolved_id = id_field
        if resolved_id is None:
            if "h3_cell" in reader.fieldnames:
                resolved_id = "h3_cell"
            elif "h3_id" in reader.fieldnames:
                resolved_id = "h3_id"
            else:
                raise ValueError("CSV must contain h3_cell or h3_id")
        if resolved_id not in reader.fieldnames:
            raise ValueError(f"CSV is missing identifier field {resolved_id!r}")
        if elevation_field not in reader.fieldnames:
            raise ValueError(f"CSV is missing elevation field {elevation_field!r}")
        return {
            row[resolved_id]: float(row[elevation_field])
            for row in reader
            if row.get(resolved_id) not in (None, "")
        }


def write_dem_csv(path: str | Path, elevation: Mapping[str, float]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["h3_cell", "elevation_m"])
        for cell, z in sorted(elevation.items()):
            writer.writerow([cell, f"{float(z):.9f}"])
    return path


def read_dem_geopackage(
    path: str | Path,
    *,
    layer: str = "cells",
    id_field: str = "h3_id",
    elevation_field: str = "elevation_m",
) -> dict[str, float]:
    try:
        import geopandas as gpd
    except ImportError as exc:  # pragma: no cover
        raise ImportError("GeoPackage input requires the GIS optional dependencies") from exc
    gdf = gpd.read_file(path, layer=layer)
    missing = {id_field, elevation_field}.difference(gdf.columns)
    if missing:
        raise ValueError(f"GeoPackage layer {layer!r} is missing fields: {sorted(missing)}")
    return {
        str(cell): float(z)
        for cell, z in zip(gdf[id_field], gdf[elevation_field])
    }


def read_dem(
    path: str | Path,
    *,
    layer: str = "cells",
    id_field: str | None = None,
    elevation_field: str = "elevation_m",
) -> dict[str, float]:
    """Read a DEM from CSV or GeoPackage based on file extension."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return read_dem_csv(path, id_field=id_field, elevation_field=elevation_field)
    if suffix == ".gpkg":
        return read_dem_geopackage(
            path,
            layer=layer,
            id_field="h3_id" if id_field is None else id_field,
            elevation_field=elevation_field,
        )
    raise ValueError("Supported DEM inputs are .csv and .gpkg")
