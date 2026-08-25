from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Callable, Hashable, Mapping, TypeVar

from .parallel import map_independent

Cell = TypeVar("Cell", bound=Hashable)


@dataclass(frozen=True, slots=True)
class FlowResult:
    """Steepest-downslope routing result for one DGGS cell."""

    cell: Hashable
    flow_to: Hashable | None
    drop: float
    distance: float
    slope: float


def flow_direction(
    cell: Cell,
    elevation: Mapping[Cell, float],
    neighbors: Callable[[Cell], list[Cell] | tuple[Cell, ...]],
    distance: Callable[[Cell, Cell], float],
) -> FlowResult:
    """Route one cell to the adjacent cell with greatest positive slope.

    Neighbors outside ``elevation`` are treated as no-data/domain boundaries.
    If no adjacent cell is lower, ``flow_to`` is ``None``.
    """
    z0 = float(elevation[cell])
    best_neighbor: Cell | None = None
    best_drop = 0.0
    best_distance = 0.0
    best_slope = 0.0

    for neighbor in neighbors(cell):
        if neighbor not in elevation:
            continue

        drop = z0 - float(elevation[neighbor])
        if drop <= 0.0:
            continue

        d = float(distance(cell, neighbor))
        if d <= 0.0:
            raise ValueError(f"Distance must be > 0 for edge {cell!r} -> {neighbor!r}")

        slope = drop / d
        if slope > best_slope:
            best_neighbor = neighbor
            best_drop = drop
            best_distance = d
            best_slope = slope

    return FlowResult(cell, best_neighbor, best_drop, best_distance, best_slope)


def compute_flow_directions(
    elevation: Mapping[Cell, float],
    neighbors: Callable[[Cell], list[Cell] | tuple[Cell, ...]],
    distance: Callable[[Cell, Cell], float],
    *,
    workers: int = 1,
    chunksize: int = 256,
) -> dict[Cell, FlowResult]:
    """Compute independent D6-style flow directions for all cells in a DEM.

    ``workers > 1`` evaluates independent source cells concurrently using the
    shared-memory thread backend.
    """
    cells = tuple(elevation)
    func = partial(
        flow_direction, elevation=elevation, neighbors=neighbors, distance=distance
    )
    results = map_independent(func, cells, workers=workers, chunksize=chunksize)
    return dict(zip(cells, results))
