from __future__ import annotations

from typing import Callable, Hashable, Mapping, TypeVar

from .base import TerrainResult
from .breach import breach_depressions
from .depressions import find_pits
from .fill import priority_flood_fill

Cell = TypeVar("Cell", bound=Hashable)
Neighbors = Callable[[Cell], list[Cell] | tuple[Cell, ...]]
Distance = Callable[[Cell, Cell], float]


def condition_dem(
    elevation: Mapping[Cell, float],
    neighbors: Neighbors,
    *,
    method: str = "hybrid",
    distance: Distance | None = None,
    min_slope: float = 1e-5,
    max_fill_depth_m: float = 2.0,
    max_breach_depth_m: float | None = 20.0,
    max_search_cells: int = 100_000,
) -> TerrainResult:
    """Hydrologically condition a DEM by filling, breaching, or a hybrid strategy.

    Hybrid mode first estimates full Priority-Flood depth. Pits deeper than
    ``max_fill_depth_m`` are offered to the least-cost breacher; a final
    Priority-Flood resolves any remaining depressions and enforces connectivity.
    """
    method = method.lower()
    if method == "fill":
        return priority_flood_fill(
            elevation, neighbors, distance=distance, min_slope=min_slope
        )
    if method == "breach":
        return breach_depressions(
            elevation,
            neighbors,
            distance=distance,
            min_slope=max(min_slope, 1e-12),
            max_breach_depth_m=max_breach_depth_m,
            max_search_cells=max_search_cells,
        )
    if method != "hybrid":
        raise ValueError("method must be one of: fill, breach, hybrid")
    if max_fill_depth_m < 0.0:
        raise ValueError("max_fill_depth_m must be >= 0")

    preview_fill = priority_flood_fill(elevation, neighbors, distance=distance, min_slope=0.0)
    fill_depth = preview_fill.diagnostics["fill_depth_m"]
    deep_pits = {
        pit
        for pit in find_pits(elevation, neighbors)
        if float(fill_depth.get(pit, 0.0)) > max_fill_depth_m
    }
    breached = breach_depressions(
        elevation,
        neighbors,
        distance=distance,
        pits=deep_pits,
        min_slope=max(min_slope, 1e-12),
        max_breach_depth_m=max_breach_depth_m,
        max_search_cells=max_search_cells,
    )
    final = priority_flood_fill(
        breached.elevation,
        neighbors,
        distance=distance,
        min_slope=min_slope,
    )

    original = {cell: float(z) for cell, z in elevation.items()}
    breach_depth = {
        cell: max(0.0, original[cell] - float(breached.elevation[cell])) for cell in original
    }
    final_fill_depth = {
        cell: max(0.0, float(final.elevation[cell]) - float(breached.elevation[cell]))
        for cell in original
    }
    return TerrainResult.from_elevation(
        original,
        final.elevation,
        diagnostics={
            "breach_depth_m": breach_depth,
            "fill_depth_m": final_fill_depth,
        },
        metadata={
            "operation": "condition",
            "method": "hybrid",
            "deep_pits_considered": len(deep_pits),
            "max_fill_depth_m": max_fill_depth_m,
            "max_breach_depth_m": max_breach_depth_m,
            "min_slope": min_slope,
        },
    )
