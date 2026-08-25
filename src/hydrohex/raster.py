from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import time
from typing import Iterable, Sequence

import numpy as np


@dataclass(frozen=True)
class RasterImportResult:
    """Result of sampling a raster DEM onto H3 cell centres."""

    elevation: dict[str, float]
    source_crs: str
    source_bounds: tuple[float, float, float, float]
    sampling: str
    h3_resolution: int
    source_path: str


def _rasterio_imports():
    try:
        import rasterio
        from rasterio.warp import transform, transform_bounds
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "Raster ingestion requires rasterio. Install with `python -m pip install -e '.[gis]'` "
            "or use environment.yml."
        ) from exc
    return rasterio, transform, transform_bounds


def _h3_import():
    try:
        import h3
    except ImportError as exc:  # pragma: no cover
        raise ImportError("Raster-to-DGGS ingestion requires the `h3` package.") from exc
    return h3


def _is_transient_file_lock(exc: BaseException) -> bool:
    """Return True for Windows/GDAL sharing violations worth retrying."""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, PermissionError) or getattr(current, "winerror", None) == 32:
            return True
        message = str(current).lower()
        if (
            "being used by another process" in message
            or "sharing violation" in message
            or "permission denied" in message
            or "winerror 32" in message
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


@contextmanager
def _open_raster_with_retry(rasterio, path: str | Path, *, retries: int = 7):
    """Open a raster, retrying brief Windows antivirus/indexer locks."""
    last_error: BaseException | None = None
    src = None
    for attempt in range(retries):
        try:
            src = rasterio.open(path)
            break
        except Exception as exc:
            if not _is_transient_file_lock(exc):
                raise
            last_error = exc
            time.sleep(0.05 * (2 ** attempt))
    if src is None:
        assert last_error is not None
        raise last_error
    try:
        yield src
    finally:
        src.close()


def _as_float_or_none(value) -> float | None:
    if value is np.ma.masked:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


def _sample_nearest(dataset, xs: Sequence[float], ys: Sequence[float], *, band: int) -> list[float | None]:
    samples = dataset.sample(zip(xs, ys), indexes=band, masked=True)
    return [_as_float_or_none(sample[0] if np.ndim(sample) else sample) for sample in samples]


def _sample_bilinear(dataset, xs: Sequence[float], ys: Sequence[float], *, band: int) -> list[float | None]:
    """Bilinear sampling at coordinates already expressed in the raster CRS."""
    data = dataset.read(band, masked=True)
    inv = ~dataset.transform
    output: list[float | None] = []

    for x, y in zip(xs, ys):
        # Affine inverse maps world coordinates to pixel corner coordinates.
        # Shift by 0.5 so integer coordinates refer to pixel centres.
        col_f = inv.a * x + inv.b * y + inv.c - 0.5
        row_f = inv.d * x + inv.e * y + inv.f - 0.5
        c0 = int(np.floor(col_f))
        r0 = int(np.floor(row_f))
        dc = float(col_f - c0)
        dr = float(row_f - r0)

        if r0 < 0 or c0 < 0 or r0 + 1 >= data.shape[0] or c0 + 1 >= data.shape[1]:
            output.append(None)
            continue

        values = (
            data[r0, c0],
            data[r0, c0 + 1],
            data[r0 + 1, c0],
            data[r0 + 1, c0 + 1],
        )
        if any(np.ma.is_masked(v) for v in values):
            output.append(None)
            continue

        z00, z10, z01, z11 = (float(v) for v in values)
        z0 = z00 * (1.0 - dc) + z10 * dc
        z1 = z01 * (1.0 - dc) + z11 * dc
        output.append(z0 * (1.0 - dr) + z1 * dr)
    return output


def sample_raster_lonlat(
    path: str | Path,
    lonlat: Sequence[tuple[float, float]],
    *,
    sampling: str = "bilinear",
    band: int = 1,
) -> list[float | None]:
    """Sample a raster at ``(longitude, latitude)`` points.

    Coordinates are always supplied in EPSG:4326. The raster may use any CRS
    understood by rasterio/GDAL.
    """
    if sampling not in {"nearest", "bilinear"}:
        raise ValueError("sampling must be 'nearest' or 'bilinear'")
    rasterio, transform, _ = _rasterio_imports()

    with _open_raster_with_retry(rasterio, path) as src:
        if src.crs is None:
            raise ValueError("Input raster has no CRS")
        if band < 1 or band > src.count:
            raise ValueError(f"Raster band {band} is outside 1..{src.count}")
        if not lonlat:
            return []
        lngs = [float(p[0]) for p in lonlat]
        lats = [float(p[1]) for p in lonlat]
        xs, ys = transform("EPSG:4326", src.crs, lngs, lats)
        if sampling == "nearest":
            return _sample_nearest(src, xs, ys, band=band)
        return _sample_bilinear(src, xs, ys, band=band)


def raster_bounds_lonlat(path: str | Path) -> tuple[float, float, float, float]:
    rasterio, _, transform_bounds = _rasterio_imports()
    with _open_raster_with_retry(rasterio, path) as src:
        if src.crs is None:
            raise ValueError("Input raster has no CRS")
        return tuple(
            float(v)
            for v in transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
        )


def h3_cells_for_raster(path: str | Path, resolution: int) -> list[str]:
    """Return H3 cells whose centres fall inside the raster's lon/lat extent."""
    if not 0 <= resolution <= 15:
        raise ValueError("H3 resolution must be between 0 and 15")
    h3 = _h3_import()
    west, south, east, north = raster_bounds_lonlat(path)
    geo = {
        "type": "Polygon",
        "coordinates": [[
            [west, south],
            [east, south],
            [east, north],
            [west, north],
            [west, south],
        ]],
    }
    # h3-py 4.x exposes geo_to_cells for GeoJSON-like polygons.
    if hasattr(h3, "geo_to_cells"):
        cells = h3.geo_to_cells(geo, resolution)
    else:  # pragma: no cover - compatibility with alternate H3 4.x APIs
        polygon = h3.LatLngPoly(
            [(south, west), (south, east), (north, east), (north, west)]
        )
        cells = h3.polygon_to_cells(polygon, resolution)
    return sorted(cells)


def raster_to_h3(
    path: str | Path,
    *,
    resolution: int = 13,
    sampling: str = "bilinear",
    band: int = 1,
    cells: Iterable[str] | None = None,
) -> RasterImportResult:
    """Sample a raster DEM onto H3 cell centres.

    H3 cells are selected by the raster's geographic extent unless an explicit
    cell iterable is supplied. Cells with NoData at their centre are omitted.
    """
    h3 = _h3_import()
    rasterio, _, _ = _rasterio_imports()
    path = Path(path)
    selected = sorted(cells) if cells is not None else h3_cells_for_raster(path, resolution)
    lonlat = []
    for cell in selected:
        lat, lng = h3.cell_to_latlng(cell)
        lonlat.append((lng, lat))
    samples = sample_raster_lonlat(path, lonlat, sampling=sampling, band=band)
    elevation = {
        cell: float(z)
        for cell, z in zip(selected, samples)
        if z is not None and np.isfinite(z)
    }
    if not elevation:
        raise ValueError("Raster sampling produced no valid H3 elevations")

    with _open_raster_with_retry(rasterio, path) as src:
        return RasterImportResult(
            elevation=elevation,
            source_crs=str(src.crs),
            source_bounds=tuple(float(v) for v in src.bounds),
            sampling=sampling,
            h3_resolution=resolution,
            source_path=str(path),
        )
