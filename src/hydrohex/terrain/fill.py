from __future__ import annotations

import heapq
from typing import Callable, Hashable, Iterable, Mapping, TypeVar

from ..accumulation import boundary_cells
from ..progress import progress_bar
from .base import TerrainResult

Cell = TypeVar("Cell", bound=Hashable)
Neighbors = Callable[[Cell], list[Cell] | tuple[Cell, ...]]
Distance = Callable[[Cell, Cell], float]


def priority_flood_fill(
    elevation: Mapping[Cell, float],
    neighbors: Neighbors,
    *,
    distance: Distance | None = None,
    outlets: Iterable[Cell] | None = None,
    min_slope: float = 0.0,
    progress: bool = False,
) -> TerrainResult:
    """Fill depressions using a graph-native Priority-Flood traversal.

    Domain-boundary cells are outlets by default. ``min_slope`` is a dimensionless
    rise/run gradient applied inward from processed lower cells; leave it at zero
    to perform a conventional flat-producing depression fill.
    """
    if min_slope < 0.0:
        raise ValueError("min_slope must be >= 0")
    original = {cell: float(z) for cell, z in elevation.items()}
    domain = set(original)
    seeds = set(outlets) if outlets is not None else boundary_cells(domain, neighbors, progress=progress)
    unknown = seeds.difference(domain)
    if unknown:
        raise ValueError(f"Unknown outlet cell {next(iter(unknown))!r}")
    if not seeds:
        raise ValueError("Priority-Flood requires at least one outlet/domain-boundary cell")

    filled = dict(original)
    visited: set[Cell] = set(seeds)
    queue: list[tuple[float, int, Cell]] = []
    serial = 0
    for cell in seeds:
        heapq.heappush(queue, (filled[cell], serial, cell))
        serial += 1

    with progress_bar(total=len(domain), desc="Priority-Flood filling", enabled=progress) as bar:
        bar.update(len(visited))
        while queue:
            spill_z, _order, cell = heapq.heappop(queue)
            for neighbor in neighbors(cell):
                if neighbor not in domain or neighbor in visited:
                    continue
                visited.add(neighbor)
                required = spill_z
                if min_slope > 0.0:
                    d = 1.0 if distance is None else float(distance(cell, neighbor))
                    if d <= 0.0:
                        raise ValueError("distance must be > 0 when min_slope is used")
                    required += min_slope * d
                filled[neighbor] = max(original[neighbor], required)
                heapq.heappush(queue, (filled[neighbor], serial, neighbor))
                serial += 1
                bar.update(1)

    if visited != domain:
        missing = domain.difference(visited)
        raise ValueError(
            f"Topology is disconnected from outlets; {len(missing)} cell(s) were not reached"
        )

    fill_depth = {cell: max(0.0, filled[cell] - original[cell]) for cell in original}
    return TerrainResult.from_elevation(
        original,
        filled,
        diagnostics={"fill_depth_m": fill_depth},
        metadata={"operation": "fill", "method": "priority_flood", "min_slope": min_slope},
    )
