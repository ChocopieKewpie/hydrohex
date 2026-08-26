from __future__ import annotations

import heapq
from typing import Callable, Hashable, Iterable, Mapping, TypeVar

from ..accumulation import boundary_cells
from ..progress import progress_bar
from .base import TerrainResult
from .depressions import find_pits

Cell = TypeVar("Cell", bound=Hashable)
Neighbors = Callable[[Cell], list[Cell] | tuple[Cell, ...]]
Distance = Callable[[Cell, Cell], float]


def _least_cost_escape_path(
    pit: Cell,
    elevation: Mapping[Cell, float],
    neighbors: Neighbors,
    boundaries: set[Cell],
    distance: Distance | None,
    max_search_cells: int,
) -> list[Cell] | None:
    """Find a low-excavation path from a pit to lower terrain or the domain edge."""
    z_pit = float(elevation[pit])
    costs: dict[Cell, float] = {pit: 0.0}
    previous: dict[Cell, Cell] = {}
    queue: list[tuple[float, int, Cell]] = [(0.0, 0, pit)]
    serial = 1
    visited: set[Cell] = set()
    target: Cell | None = None

    while queue and len(visited) < max_search_cells:
        cost, _order, cell = heapq.heappop(queue)
        if cell in visited:
            continue
        visited.add(cell)
        if cell != pit and (float(elevation[cell]) < z_pit or cell in boundaries):
            target = cell
            break
        for n in neighbors(cell):
            if n not in elevation or n in visited:
                continue
            d = 1.0 if distance is None else float(distance(cell, n))
            if d <= 0.0:
                raise ValueError("distance must be > 0")
            # Proxy excavation cost: terrain above the pit floor is expensive,
            # weighted by edge length. Terrain already below the pit is free.
            excavation = max(0.0, float(elevation[n]) - z_pit) * d
            new_cost = cost + excavation + 1e-12 * d
            if new_cost < costs.get(n, float("inf")):
                costs[n] = new_cost
                previous[n] = cell
                heapq.heappush(queue, (new_cost, serial, n))
                serial += 1

    if target is None:
        return None
    path = [target]
    while path[-1] != pit:
        path.append(previous[path[-1]])
    path.reverse()
    return path


def breach_depressions(
    elevation: Mapping[Cell, float],
    neighbors: Neighbors,
    *,
    distance: Distance | None = None,
    pits: Iterable[Cell] | None = None,
    min_slope: float = 1e-5,
    max_breach_depth_m: float | None = None,
    max_search_cells: int = 100_000,
    progress: bool = False,
) -> TerrainResult:
    """Carve least-cost drainage paths from local pits.

    This first graph-native breacher searches from each strict pit to either lower
    terrain or a domain-boundary cell, then lowers cells along that path to a
    monotonically descending profile. Paths exceeding ``max_breach_depth_m`` are
    left unchanged. Pits are processed sequentially because breaches alter the DEM.
    """
    if min_slope <= 0.0:
        raise ValueError("min_slope must be > 0")
    if max_breach_depth_m is not None and max_breach_depth_m < 0.0:
        raise ValueError("max_breach_depth_m must be >= 0")
    if max_search_cells < 1:
        raise ValueError("max_search_cells must be >= 1")

    original = {cell: float(z) for cell, z in elevation.items()}
    current = dict(original)
    boundaries = boundary_cells(set(current), neighbors, progress=progress)
    selected = list(find_pits(current, neighbors) if pits is None else pits)
    total_carve = {cell: 0.0 for cell in current}
    breached_pits = 0

    with progress_bar(total=len(selected), desc="Breaching depressions", enabled=progress, unit="pit") as bar:
        for pit in selected:
            try:
                if pit not in current or pit in boundaries:
                    continue
                path = _least_cost_escape_path(
                    pit, current, neighbors, boundaries, distance, max_search_cells
                )
                if path is None or len(path) < 2:
                    continue

                profile: dict[Cell, float] = {pit: current[pit]}
                cumulative = 0.0
                prev = pit
                for cell in path[1:]:
                    d = 1.0 if distance is None else float(distance(prev, cell))
                    cumulative += d
                    profile[cell] = current[pit] - min_slope * cumulative
                    prev = cell

                depths = {cell: max(0.0, current[cell] - profile[cell]) for cell in path[1:]}
                required_depth = max(depths.values(), default=0.0)
                if max_breach_depth_m is not None and required_depth > max_breach_depth_m:
                    continue

                changed = False
                for cell in path[1:]:
                    new_z = min(current[cell], profile[cell])
                    if new_z < current[cell]:
                        total_carve[cell] += current[cell] - new_z
                        current[cell] = new_z
                        changed = True
                if changed:
                    breached_pits += 1
            finally:
                bar.update(1)

    breach_depth = {cell: max(0.0, original[cell] - current[cell]) for cell in current}
    return TerrainResult.from_elevation(
        original,
        current,
        diagnostics={"breach_depth_m": breach_depth},
        metadata={
            "operation": "breach",
            "method": "least_cost",
            "breached_pits": breached_pits,
            "requested_pits": len(selected),
            "min_slope": min_slope,
            "max_breach_depth_m": max_breach_depth_m,
        },
    )
