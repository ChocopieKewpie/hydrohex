from __future__ import annotations

import json
import math
import os
import time
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

USGS_3DEP_IMAGE_SERVER = (
    "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
)

# Loch Vale watershed, Rocky Mountain National Park, with a modest buffer around
# the ~6.6 km² alpine/subalpine basin. The box remains below the ImageServer's
# published 8000 x 8000 export limit at the 1 m default request spacing.
DEFAULT_LOCH_VALE_BBOX = (-105.688, 40.266, -105.645, 40.301)

# Retained as an optional comparison/stress-test site.
DEFAULT_BOULDER_BBOX = (-105.33, 39.99, -105.23, 40.05)

DEFAULT_REAL_DEM_SITE = "loch-vale"
DEFAULT_PIXEL_SIZE_M = 1.0
REAL_DEM_SITES: dict[str, tuple[float, float, float, float]] = {
    "loch-vale": DEFAULT_LOCH_VALE_BBOX,
    "boulder": DEFAULT_BOULDER_BBOX,
}

EARTH_RADIUS_M = 6_371_008.8
MAX_IMAGE_SIZE = 8000
# In practice the dynamic ImageServer can reject large float32 TIFF exports with
# HTTP 500 even when width/height are below its advertised limit. Keep individual
# requests modest and mosaic them locally.
DEFAULT_TILE_SIZE = 1024
RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class USGSFetchMetadata:
    source: str
    bbox_lonlat: tuple[float, float, float, float]
    requested_pixel_size_m: float
    width: int
    height: int
    url: str
    delivery_mode: str = "direct"
    tile_count: int = 1


def site_bbox(site: str = DEFAULT_REAL_DEM_SITE) -> tuple[float, float, float, float]:
    """Return a built-in real-DEM benchmark bounding box."""
    try:
        return REAL_DEM_SITES[site]
    except KeyError as exc:
        choices = ", ".join(sorted(REAL_DEM_SITES))
        raise ValueError(f"unknown site {site!r}; choose one of: {choices}") from exc


def _great_circle_m(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = phi2 - phi1
    dlambda = math.radians(lng2 - lng1)
    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def _export_url_for_size(
    bbox: tuple[float, float, float, float],
    *,
    width: int,
    height: int,
) -> str:
    west, south, east, north = bbox
    params = {
        "bbox": f"{west:.10f},{south:.10f},{east:.10f},{north:.10f}",
        "bboxSR": "4326",
        "imageSR": "4326",
        "size": f"{int(width)},{int(height)}",
        "format": "tiff",
        "pixelType": "F32",
        "noData": "-9999",
        "interpolation": "RSP_BilinearInterpolation",
        # ArcGIS otherwise may expand/shift geographic extents to make pixels
        # square in angular units. Our requested width/height are chosen to
        # approximate square metres on the ground, so that adjustment creates
        # tile-to-tile geolocation discontinuities.
        "returnSquarePixels": "false",
        "f": "image",
    }
    return f"{USGS_3DEP_IMAGE_SERVER}?{urlencode(params)}"


def build_usgs_3dep_export_url(
    bbox: tuple[float, float, float, float],
    *,
    pixel_size_m: float = DEFAULT_PIXEL_SIZE_M,
) -> tuple[str, USGSFetchMetadata]:
    """Build a float32 GeoTIFF export request against the USGS 3DEP ImageServer.

    ``pixel_size_m`` is a requested ground-sampling interval used to derive the
    export dimensions. The dynamic 3DEP service mosaics the best available
    source data; a 1 m request does not guarantee native 1 m source coverage.
    Large exports are downloaded as smaller tiles by :func:`fetch_usgs_3dep`.
    """
    west, south, east, north = (float(v) for v in bbox)
    if not west < east or not south < north:
        raise ValueError("bbox must be west,south,east,north")
    if pixel_size_m <= 0:
        raise ValueError("pixel_size_m must be > 0")

    mid_lat = (south + north) / 2.0
    mid_lng = (west + east) / 2.0
    ground_width_m = _great_circle_m(west, mid_lat, east, mid_lat)
    ground_height_m = _great_circle_m(mid_lng, south, mid_lng, north)
    width = max(1, int(math.ceil(ground_width_m / pixel_size_m)))
    height = max(1, int(math.ceil(ground_height_m / pixel_size_m)))
    if width > MAX_IMAGE_SIZE or height > MAX_IMAGE_SIZE:
        raise ValueError(
            f"Requested USGS export is {width}x{height}; service limit is "
            f"{MAX_IMAGE_SIZE}x{MAX_IMAGE_SIZE}. Use a smaller bbox or larger pixel size."
        )

    bbox_tuple = (west, south, east, north)
    url = _export_url_for_size(bbox_tuple, width=width, height=height)
    metadata = USGSFetchMetadata(
        source="USGS 3DEP Dynamic Elevation ImageServer (best available mosaic)",
        bbox_lonlat=bbox_tuple,
        requested_pixel_size_m=float(pixel_size_m),
        width=width,
        height=height,
        url=url,
    )
    return url, metadata


def _looks_like_tiff_bytes(payload: bytes) -> bool:
    return payload[:4] in {b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"}


def _looks_like_tiff(path: Path) -> bool:
    with path.open("rb") as f:
        return _looks_like_tiff_bytes(f.read(4))


def _remove_partial_download(path: Path, *, retries: int = 5) -> bool:
    """Best-effort removal of a failed direct download without masking its error."""
    for attempt in range(retries):
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError as exc:
            is_windows_share_lock = getattr(exc, "winerror", None) == 32
            if not isinstance(exc, PermissionError) and not is_windows_share_lock:
                return False
            time.sleep(0.05 * (2 ** attempt))
    return False


def _open_output_for_write(path: Path, *, retries: int = 7):
    """Open a destination for binary write, retrying transient Windows sharing locks."""
    last_error: OSError | None = None
    for attempt in range(retries):
        try:
            return path.open("wb")
        except OSError as exc:
            is_windows_share_lock = getattr(exc, "winerror", None) == 32
            if not isinstance(exc, PermissionError) and not is_windows_share_lock:
                raise
            last_error = exc
            time.sleep(0.05 * (2 ** attempt))
    assert last_error is not None
    raise last_error


def _http_error_detail(exc: HTTPError) -> str:
    try:
        body = exc.read(2000).decode("utf-8", errors="replace").strip()
    except Exception:
        body = ""
    return body


def _fetch_tiff_bytes(
    url: str,
    *,
    timeout_s: int,
    retries: int = 4,
) -> bytes:
    """Fetch one small TIFF request with retries for transient ArcGIS failures."""
    last_error: Exception | None = None
    for attempt in range(retries):
        request = Request(url, headers={"User-Agent": "hydrohex/0.1.0 (+USGS-3DEP-test)"})
        try:
            with urlopen(request, timeout=timeout_s) as response:
                payload = response.read()
            if not _looks_like_tiff_bytes(payload):
                preview = payload[:500]
                raise RuntimeError(f"USGS export did not return a GeoTIFF: {preview!r}")
            return payload
        except HTTPError as exc:
            detail = _http_error_detail(exc)
            last_error = RuntimeError(
                f"USGS 3DEP export failed with HTTP {exc.code}"
                + (f": {detail}" if detail else "")
            )
            if exc.code not in RETRYABLE_HTTP_CODES or attempt == retries - 1:
                raise last_error from exc
        except URLError as exc:
            last_error = exc
            if attempt == retries - 1:
                raise
        if attempt < retries - 1:
            time.sleep(0.5 * (2 ** attempt))
    assert last_error is not None
    raise last_error


def _tile_windows(width: int, height: int, tile_size: int):
    for y0 in range(0, height, tile_size):
        y1 = min(height, y0 + tile_size)
        for x0 in range(0, width, tile_size):
            x1 = min(width, x0 + tile_size)
            yield x0, y0, x1, y1


def _tile_bbox(
    bbox: tuple[float, float, float, float],
    *,
    width: int,
    height: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
) -> tuple[float, float, float, float]:
    west, south, east, north = bbox
    dx = east - west
    dy = north - south
    tile_west = west + dx * (x0 / width)
    tile_east = west + dx * (x1 / width)
    tile_north = north - dy * (y0 / height)
    tile_south = north - dy * (y1 / height)
    return tile_west, tile_south, tile_east, tile_north


def _fetch_tiled_mosaic(
    output: Path,
    *,
    metadata: USGSFetchMetadata,
    timeout_s: int,
    tile_size: int,
) -> int:
    """Fetch small 3DEP TIFF tiles and assemble an exact output grid locally."""
    try:
        import numpy as np
        import rasterio
        from rasterio.io import MemoryFile
        from rasterio.transform import from_bounds
        from rasterio.windows import Window, transform as window_transform
        from rasterio.warp import reproject, Resampling
    except ImportError as exc:  # pragma: no cover - package dependency guard
        raise RuntimeError("Tiled USGS downloads require numpy and rasterio") from exc

    width, height = metadata.width, metadata.height
    west, south, east, north = metadata.bbox_lonlat
    nodata = -9999.0
    mosaic = np.full((height, width), nodata, dtype="float32")
    count = 0
    # All tiles are resampled onto this single target transform. Do not assume
    # ArcGIS returns the exact requested transform: exportImage can adjust a
    # geographic tile extent/pixel geometry even when the requested array size
    # is correct. Blind array pasting creates artificial steps at tile seams.
    transform = from_bounds(west, south, east, north, width, height)

    for x0, y0, x1, y1 in _tile_windows(width, height, tile_size):
        tile_width = x1 - x0
        tile_height = y1 - y0
        bbox = _tile_bbox(
            metadata.bbox_lonlat,
            width=width,
            height=height,
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
        )
        url = _export_url_for_size(bbox, width=tile_width, height=tile_height)
        payload = _fetch_tiff_bytes(url, timeout_s=timeout_s)
        tile = np.full((tile_height, tile_width), nodata, dtype="float32")
        dst_transform = window_transform(
            Window(x0, y0, tile_width, tile_height),
            transform,
        )
        with MemoryFile(payload) as memfile:
            with memfile.open() as src:
                if src.crs is None:
                    raise RuntimeError("USGS tile has no CRS; cannot align tiled mosaic safely")
                reproject(
                    source=rasterio.band(src, 1),
                    destination=tile,
                    src_transform=src.transform,
                    src_crs=src.crs,
                    src_nodata=src.nodata,
                    dst_transform=dst_transform,
                    dst_crs="EPSG:4326",
                    dst_nodata=nodata,
                    resampling=Resampling.bilinear,
                    init_dest_nodata=True,
                )
        mosaic[y0:y1, x0:x1] = tile
        count += 1

    profile = {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": transform,
        "nodata": nodata,
        "compress": "deflate",
        "predictor": 3,
        "BIGTIFF": "IF_SAFER",
    }
    with rasterio.open(output, "w", **profile) as dst:
        dst.write(mosaic, 1)
    return count


def _fetch_direct_to_path(output: Path, *, url: str, timeout_s: int) -> None:
    payload = _fetch_tiff_bytes(url, timeout_s=timeout_s)
    with _open_output_for_write(output) as dst:
        dst.write(payload)
        dst.flush()
        os.fsync(dst.fileno())


def fetch_usgs_3dep(
    output_path: str | Path,
    *,
    bbox: tuple[float, float, float, float] = DEFAULT_LOCH_VALE_BBOX,
    pixel_size_m: float = DEFAULT_PIXEL_SIZE_M,
    overwrite: bool = False,
    timeout_s: int = 180,
    tile_size: int = DEFAULT_TILE_SIZE,
) -> USGSFetchMetadata:
    """Download a clipped USGS 3DEP float32 GeoTIFF and write a JSON sidecar.

    Small exports are fetched directly. Larger exports are automatically split
    into modest TIFF requests and assembled locally. ArcGIS ImageServer can
    return HTTP 500 for large float32 TIFF exports even below its advertised
    8000 x 8000 width/height limit, so tiling is the default for large AOIs.
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    sidecar = output.with_suffix(output.suffix + ".json")
    if output.exists() and not overwrite:
        raise FileExistsError(f"Output exists: {output}; pass overwrite=True to replace it")
    if tile_size < 128 or tile_size > MAX_IMAGE_SIZE:
        raise ValueError(f"tile_size must be between 128 and {MAX_IMAGE_SIZE}")

    url, base_metadata = build_usgs_3dep_export_url(bbox, pixel_size_m=pixel_size_m)

    try:
        sidecar.unlink(missing_ok=True)
    except OSError:
        pass
    if overwrite:
        _remove_partial_download(output)

    use_tiled = base_metadata.width > tile_size or base_metadata.height > tile_size
    try:
        if use_tiled:
            tile_count = _fetch_tiled_mosaic(
                output,
                metadata=base_metadata,
                timeout_s=timeout_s,
                tile_size=tile_size,
            )
            metadata = USGSFetchMetadata(
                **{**asdict(base_metadata), "delivery_mode": "tiled", "tile_count": tile_count}
            )
        else:
            _fetch_direct_to_path(output, url=url, timeout_s=timeout_s)
            metadata = base_metadata
    except Exception:
        removed = _remove_partial_download(output)
        if not removed:
            warnings.warn(
                f"Download failed and partial file {output} could not be removed because "
                "another Windows process is using it. It has no metadata sidecar and will "
                "not be treated as a completed download.",
                RuntimeWarning,
                stacklevel=2,
            )
        raise

    # Validate after every writer/MemoryFile/GDAL handle is closed.
    last_error: OSError | None = None
    for attempt in range(7):
        try:
            if not _looks_like_tiff(output):
                preview = output.read_bytes()[:500]
                _remove_partial_download(output)
                raise RuntimeError(f"USGS export did not return a GeoTIFF: {preview!r}")
            last_error = None
            break
        except OSError as exc:
            is_windows_share_lock = getattr(exc, "winerror", None) == 32
            if not isinstance(exc, PermissionError) and not is_windows_share_lock:
                raise
            last_error = exc
            time.sleep(0.05 * (2 ** attempt))
    if last_error is not None:
        raise last_error

    sidecar.write_text(json.dumps(asdict(metadata), indent=2), encoding="utf-8")
    return metadata
