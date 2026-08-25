from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Callable

import h3


DEFAULT_LAT = -36.8485
DEFAULT_LNG = 174.7633
DEFAULT_RESOLUTION = 12
DEFAULT_RADIUS = 220
REFERENCE_RESOLUTION = 8
REFERENCE_RADIUS = 4


def equivalent_disk_radius(
    target_resolution: int,
    reference_resolution: int = REFERENCE_RESOLUTION,
    reference_radius: int = REFERENCE_RADIUS,
) -> int:
    """Approximate a grid-disk radius with the same physical footprint.

    H3 cell area shrinks by about 7x per resolution level, so linear scale
    shrinks by sqrt(7).  The +0.5 term accounts for the outer half-cell
    footprint of a disk whose centers extend ``reference_radius`` grid steps.
    """
    levels = target_resolution - reference_resolution
    scale = math.sqrt(7.0) ** levels
    return max(0, round((reference_radius + 0.5) * scale - 0.5))


def disk_cells(lat: float, lng: float, resolution: int, radius: int) -> list[str]:
    center = h3.latlng_to_cell(lat, lng, resolution)
    return sorted(h3.grid_disk(center, radius))


def _xy_m(cell: str, origin: str) -> tuple[float, float]:
    """Approximate local east/north coordinates from center lat/lng."""
    lat, lng = h3.cell_to_latlng(cell)
    lat0, lng0 = h3.cell_to_latlng(origin)
    earth_r = 6_371_008.8
    y = math.radians(lat - lat0) * earth_r
    x = math.radians(lng - lng0) * earth_r * math.cos(math.radians((lat + lat0) / 2.0))
    return x, y


def make_plane(cells: list[str], origin: str, z0: float = 1000.0) -> dict[str, float]:
    """Plane descending toward local east-southeast."""
    dem = {}
    for c in cells:
        x, y = _xy_m(c, origin)
        dem[c] = z0 - 0.020 * x - 0.008 * y
    return dem


def make_bowl(cells: list[str], origin: str, z0: float = 100.0) -> dict[str, float]:
    """Closed depression with its minimum near the center cell."""
    dem = {}
    for c in cells:
        x, y = _xy_m(c, origin)
        dem[c] = z0 + 0.00003 * (x * x + y * y)
    return dem


def make_ridge(cells: list[str], origin: str, z0: float = 800.0) -> dict[str, float]:
    """North-south ridge; elevations fall away to east and west."""
    dem = {}
    for c in cells:
        x, y = _xy_m(c, origin)
        dem[c] = z0 - 0.025 * abs(x) - 0.002 * y
    return dem


def make_cone(cells: list[str], origin: str, z0: float = 1000.0) -> dict[str, float]:
    """Radial hill whose summit is near the center cell."""
    dem = {}
    for c in cells:
        x, y = _xy_m(c, origin)
        dem[c] = z0 - 0.02 * math.hypot(x, y)
    return dem



GENERATORS: dict[str, Callable[[list[str], str], dict[str, float]]] = {
    "plane": make_plane,
    "bowl": make_bowl,
    "ridge": make_ridge,
    "cone": make_cone,
}


def write_csv(path: Path, dem: dict[str, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["h3_cell", "elevation_m"])
        for cell_id, z in sorted(dem.items()):
            writer.writerow([cell_id, f"{z:.6f}"])


def generate_suite(
    output_dir: Path,
    lat: float = DEFAULT_LAT,
    lng: float = DEFAULT_LNG,
    resolution: int = DEFAULT_RESOLUTION,
    radius: int | None = None,
) -> list[Path]:
    """Generate deterministic analytic DEMs used for correctness tests."""
    if radius is None:
        radius = equivalent_disk_radius(resolution)
    origin = h3.latlng_to_cell(lat, lng, resolution)
    cells = sorted(h3.grid_disk(origin, radius))
    outputs = []
    for name, generator in GENERATORS.items():
        path = output_dir / f"h3_r{resolution}_{name}.csv"
        write_csv(path, generator(cells, origin))
        outputs.append(path)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic analytic H3 DEM test datasets.")
    parser.add_argument("--output-dir", type=Path, default=Path("data/generated"))
    parser.add_argument("--lat", type=float, default=DEFAULT_LAT)
    parser.add_argument("--lng", type=float, default=DEFAULT_LNG)
    parser.add_argument("--resolution", type=int, default=DEFAULT_RESOLUTION)
    parser.add_argument(
        "--radius",
        type=int,
        default=None,
        help="Grid radius. Defaults to a value matching the original res-8/radius-4 footprint.",
    )
    args = parser.parse_args()
    for path in generate_suite(
        args.output_dir,
        args.lat,
        args.lng,
        args.resolution,
        args.radius,
    ):
        print(path)


if __name__ == "__main__":
    main()
