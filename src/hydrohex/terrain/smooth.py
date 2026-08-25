from __future__ import annotations

import math
import statistics
from functools import partial
from typing import Callable, Hashable, Mapping, TypeVar

from ..parallel import map_independent
from .base import TerrainResult

Cell = TypeVar("Cell", bound=Hashable)
Neighbors = Callable[[Cell], list[Cell] | tuple[Cell, ...]]
Distance = Callable[[Cell, Cell], float]


def _smooth_one(
    cell: Cell,
    elevation: Mapping[Cell, float],
    neighbors: Neighbors,
    distance: Distance | None,
    method: str,
    spatial_sigma: float,
    elevation_sigma: float,
) -> tuple[Cell, float]:
    z0 = float(elevation[cell])
    ring = [n for n in neighbors(cell) if n in elevation]
    values = [float(elevation[n]) for n in ring]
    if method == "mean":
        return cell, (z0 + sum(values)) / (len(values) + 1)
    if method == "median":
        return cell, float(statistics.median([z0, *values]))
    if method != "bilateral":
        raise ValueError(f"Unknown smoothing method: {method}")

    total_w = 1.0
    total_z = z0
    for neighbor in ring:
        zn = float(elevation[neighbor])
        d = 1.0 if distance is None else float(distance(cell, neighbor))
        if d < 0.0:
            raise ValueError("distance must be >= 0")
        spatial_w = math.exp(-0.5 * (d / spatial_sigma) ** 2)
        range_w = math.exp(-0.5 * ((zn - z0) / elevation_sigma) ** 2)
        w = spatial_w * range_w
        total_w += w
        total_z += w * zn
    return cell, total_z / total_w


def smooth_dem(
    elevation: Mapping[Cell, float],
    neighbors: Neighbors,
    *,
    method: str = "bilateral",
    distance: Distance | None = None,
    spatial_sigma: float = 30.0,
    elevation_sigma: float = 5.0,
    iterations: int = 1,
    workers: int = 1,
) -> TerrainResult:
    """Smooth a DGGS DEM using mean, median, or feature-preserving bilateral filtering.

    Each iteration reads one immutable elevation field and writes a new field, so
    cells within an iteration can be evaluated independently and threaded safely.
    """
    method = method.lower()
    if method not in {"mean", "median", "bilateral"}:
        raise ValueError("method must be one of: mean, median, bilateral")
    if iterations < 1:
        raise ValueError("iterations must be >= 1")
    if spatial_sigma <= 0.0:
        raise ValueError("spatial_sigma must be > 0")
    if elevation_sigma <= 0.0:
        raise ValueError("elevation_sigma must be > 0")

    original = {cell: float(z) for cell, z in elevation.items()}
    current = dict(original)
    cells = tuple(current)
    for _ in range(iterations):
        func = partial(
            _smooth_one,
            elevation=current,
            neighbors=neighbors,
            distance=distance,
            method=method,
            spatial_sigma=spatial_sigma,
            elevation_sigma=elevation_sigma,
        )
        current = dict(map_independent(func, cells, workers=workers))

    return TerrainResult.from_elevation(
        original,
        current,
        metadata={
            "operation": "smooth",
            "method": method,
            "iterations": iterations,
            "workers": workers,
            "spatial_sigma": spatial_sigma,
            "elevation_sigma": elevation_sigma,
        },
    )
