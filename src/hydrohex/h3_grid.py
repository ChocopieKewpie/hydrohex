from __future__ import annotations

import math

import h3

EARTH_RADIUS_M = 6_371_008.8


def neighbors(cell: str) -> list[str]:
    """Immediate H3 neighbors; pentagons naturally return five."""
    return [n for n in h3.grid_disk(cell, 1) if n != cell]


def distance_m(cell_a: str, cell_b: str) -> float:
    """Great-circle distance between H3 cell centers in metres."""
    a = h3.cell_to_latlng(cell_a)
    b = h3.cell_to_latlng(cell_b)
    return float(h3.great_circle_distance(a, b, unit="m"))


def local_xy_m(cell: str, origin: str) -> tuple[float, float]:
    """Approximate local east/north coordinates of ``cell`` relative to ``origin``.

    This local tangent-plane approximation is appropriate for immediate H3
    neighbors and keeps the D-infinity facet math independent of a projected CRS.
    """
    lat, lng = h3.cell_to_latlng(cell)
    lat0, lng0 = h3.cell_to_latlng(origin)
    dlng = ((lng - lng0 + 180.0) % 360.0) - 180.0
    y = math.radians(lat - lat0) * EARTH_RADIUS_M
    x = math.radians(dlng) * EARTH_RADIUS_M * math.cos(math.radians((lat + lat0) / 2.0))
    return x, y


def cell(lat: float, lng: float, resolution: int) -> str:
    return h3.latlng_to_cell(lat, lng, resolution)


def cell_area_m2(cell: str) -> float:
    """Exact spherical H3 cell area in square metres."""
    return float(h3.cell_area(cell, unit="m^2"))
