from __future__ import annotations

import csv
import math
import re
from numbers import Integral
from pathlib import Path
from typing import Iterable, Mapping

_H3_RESOLUTION_FIELD = re.compile(r"^h3_(\d{1,2})$", re.IGNORECASE)
_PARQUET_SUFFIXES = {".parquet", ".pq", ".geoparquet"}


def read_dem_csv(
    path: str | Path,
    *,
    id_field: str | None = None,
    elevation_field: str | None = None,
) -> dict[str, float]:
    """Read an H3 DEM CSV.

    The identifier field defaults to ``h3_cell`` when present, otherwise ``h3_id``.
    The elevation field defaults to ``elevation_m``.
    """
    elevation_field = "elevation_m" if elevation_field is None else elevation_field
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
        result: dict[str, float] = {}
        for row in reader:
            cell = row.get(resolved_id)
            value = row.get(elevation_field)
            if cell in (None, "") or value in (None, ""):
                continue
            z = float(value)
            if math.isfinite(z):
                result[str(cell)] = z
        return result


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
    result: dict[str, float] = {}
    for cell, value in zip(gdf[id_field], gdf[elevation_field]):
        if cell is None or value is None:
            continue
        z = float(value)
        if math.isfinite(z):
            result[_normalise_h3_cell(cell)] = z
    return result


def _normalise_h3_cell(value: object) -> str:
    """Return an H3 cell in the canonical hexadecimal string form.

    ``raster2dggs`` can emit either string or uint64 H3 identifiers. H3's integer
    representation is simply the unsigned integer form of the canonical hex ID,
    so formatting it as lowercase hexadecimal avoids a second conversion step.
    """
    if isinstance(value, Integral):
        return format(int(value), "x")
    return str(value)


def _choose_h3_field(field_names: Iterable[str], explicit: str | None = None) -> str:
    names = list(field_names)
    if explicit is not None:
        if explicit not in names:
            raise ValueError(f"Parquet dataset is missing identifier field {explicit!r}")
        return explicit

    # raster2dggs writes target and parent H3 fields as h3_XX. The target field is
    # the finest/highest resolution, while lower-resolution fields can be Hive
    # partition keys. Always choose the highest resolution automatically.
    resolution_fields: list[tuple[int, str]] = []
    for name in names:
        match = _H3_RESOLUTION_FIELD.match(name)
        if match:
            resolution_fields.append((int(match.group(1)), name))
    if resolution_fields:
        return max(resolution_fields)[1]

    for fallback in ("h3_cell", "h3_id"):
        if fallback in names:
            return fallback
    raise ValueError(
        "Could not detect an H3 identifier field. Expected h3_XX, h3_cell, or h3_id; "
        "use --id-field to override."
    )


def _choose_elevation_field(
    field_names: Iterable[str],
    numeric_fields: Iterable[str],
    explicit: str | None = None,
) -> str:
    names = list(field_names)
    numeric = set(numeric_fields)
    if explicit is not None:
        if explicit not in names:
            raise ValueError(f"Parquet dataset is missing elevation field {explicit!r}")
        if explicit not in numeric:
            raise ValueError(
                f"Parquet elevation field {explicit!r} is not a scalar numeric column"
            )
        return explicit

    # Common HydroHex names first, then raster2dggs's default one-band schema.
    for preferred in ("elevation_m", "elevation", "dem", "band_1"):
        if preferred in numeric:
            return preferred

    # If there is exactly one scalar numeric value column, it is unambiguous.
    ignored = {name for name in names if _H3_RESOLUTION_FIELD.match(name)}
    ignored.update({"h3_cell", "h3_id"})
    candidates = sorted(numeric.difference(ignored))
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError(
            "Could not detect a scalar numeric elevation column in the Parquet dataset; "
            "use --elevation-field to select one."
        )
    raise ValueError(
        "Parquet dataset has multiple numeric value columns and elevation is ambiguous: "
        f"{candidates}. Use --elevation-field."
    )


def _contains_parquet_files(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        next(path.rglob("*.parquet"))
        return True
    except StopIteration:
        return False


def read_dem_parquet(
    path: str | Path,
    *,
    id_field: str | None = None,
    elevation_field: str | None = None,
) -> dict[str, float]:
    """Read a DEM from a Parquet/GeoParquet file or partitioned dataset directory.

    This reader is designed to consume ``raster2dggs`` output directly. Hive
    partition columns are discovered, the finest ``h3_XX`` identifier is selected,
    geometry is ignored, and only the H3/elevation columns are loaded into memory.
    """
    try:
        import pyarrow as pa
        import pyarrow.dataset as ds
    except ImportError as exc:  # pragma: no cover - depends on optional runtime
        raise ImportError(
            "Parquet input requires pyarrow. Install/update HydroHex with its normal "
            "dependencies or run `conda install -c conda-forge pyarrow`."
        ) from exc

    path = Path(path)
    if not path.exists():
        raise ValueError(f"Parquet input does not exist: {path}")
    if path.is_dir() and not _contains_parquet_files(path):
        raise ValueError(f"Directory contains no .parquet files: {path}")

    try:
        dataset = ds.dataset(path, format="parquet", partitioning="hive")
    except Exception as exc:
        raise ValueError(f"Could not open Parquet dataset {path}: {exc}") from exc

    schema = dataset.schema
    field_names = schema.names
    numeric_fields = {
        field.name
        for field in schema
        if (
            pa.types.is_integer(field.type)
            or pa.types.is_floating(field.type)
            or pa.types.is_decimal(field.type)
        )
    }
    resolved_id = _choose_h3_field(field_names, id_field)
    resolved_elevation = _choose_elevation_field(
        field_names, numeric_fields, elevation_field
    )

    try:
        table = dataset.to_table(columns=[resolved_id, resolved_elevation])
    except Exception as exc:
        raise ValueError(
            f"Could not read Parquet fields {resolved_id!r} and {resolved_elevation!r}: {exc}"
        ) from exc

    cells = table[resolved_id].to_pylist()
    values = table[resolved_elevation].to_pylist()
    result: dict[str, float] = {}
    for cell, value in zip(cells, values):
        if cell is None or value is None:
            continue
        z = float(value)
        if not math.isfinite(z):
            continue
        key = _normalise_h3_cell(cell)
        if key in result:
            raise ValueError(
                f"Parquet input contains duplicate H3 cell {key!r}; compacted or overlapping "
                "inputs are not supported for flow routing."
            )
        result[key] = z
    if not result:
        raise ValueError("Parquet input contains no finite H3 elevation values")
    return result


def read_dem(
    path: str | Path,
    *,
    layer: str = "cells",
    id_field: str | None = None,
    elevation_field: str | None = None,
) -> dict[str, float]:
    """Read a DEM from CSV, GeoPackage, Parquet/GeoParquet, or a Parquet directory."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return read_dem_csv(path, id_field=id_field, elevation_field=elevation_field)
    if suffix == ".gpkg":
        return read_dem_geopackage(
            path,
            layer=layer,
            id_field="h3_id" if id_field is None else id_field,
            elevation_field="elevation_m" if elevation_field is None else elevation_field,
        )
    if suffix in _PARQUET_SUFFIXES or path.is_dir():
        return read_dem_parquet(
            path,
            id_field=id_field,
            elevation_field=elevation_field,
        )
    raise ValueError(
        "Supported DEM inputs are .csv, .gpkg, .parquet/.pq/.geoparquet, or a "
        "partitioned Parquet dataset directory"
    )
