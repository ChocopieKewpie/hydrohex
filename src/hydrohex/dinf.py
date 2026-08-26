from __future__ import annotations

import math
from dataclasses import dataclass
from functools import partial
from typing import Callable, Hashable, Mapping, TypeVar

from .parallel import map_independent

Cell = TypeVar("Cell", bound=Hashable)
XY = Callable[[Cell, Cell], tuple[float, float]]
Neighbors = Callable[[Cell], list[Cell] | tuple[Cell, ...]]


@dataclass(frozen=True, slots=True)
class DInfFlowResult:
    """Facet-based D-infinity routing result for one DGGS cell.

    ``direction_rad`` is a mathematical angle in the local tangent plane:
    0 = east and positive angles rotate counter-clockwise toward north.
    Fractions sum to one when one or two receivers exist.
    """

    cell: Hashable
    direction_rad: float | None
    slope: float
    receiver_1: Hashable | None
    fraction_1: float
    receiver_2: Hashable | None
    fraction_2: float

    @property
    def sink(self) -> bool:
        return self.receiver_1 is None

    @property
    def receivers(self) -> tuple[tuple[Hashable, float], ...]:
        out: list[tuple[Hashable, float]] = []
        if self.receiver_1 is not None and self.fraction_1 > 0.0:
            out.append((self.receiver_1, self.fraction_1))
        if self.receiver_2 is not None and self.fraction_2 > 0.0:
            out.append((self.receiver_2, self.fraction_2))
        return tuple(out)


def _angle(x: float, y: float) -> float:
    return math.atan2(y, x) % (2.0 * math.pi)


def ordered_neighbors(cell: Cell, neighbors: Neighbors, xy: XY) -> list[Cell]:
    """Return immediate neighbors counter-clockwise around ``cell``."""
    items = []
    for neighbor in neighbors(cell):
        x, y = xy(neighbor, cell)
        if x == 0.0 and y == 0.0:
            raise ValueError(f"Neighbor {neighbor!r} has same coordinates as {cell!r}")
        items.append((_angle(x, y), neighbor))
    items.sort(key=lambda item: item[0])
    return [neighbor for _, neighbor in items]


def _edge_candidate(
    neighbor: Cell,
    z0: float,
    elevation: Mapping[Cell, float],
    xy: XY,
    cell: Cell,
) -> tuple[float, float] | None:
    if neighbor not in elevation:
        return None
    drop = z0 - float(elevation[neighbor])
    if drop <= 0.0:
        return None
    x, y = xy(neighbor, cell)
    distance = math.hypot(x, y)
    if distance <= 0.0:
        raise ValueError(f"Distance must be > 0 for edge {cell!r} -> {neighbor!r}")
    return drop / distance, _angle(x, y)


def dinf_flow_direction(
    cell: Cell,
    elevation: Mapping[Cell, float],
    neighbors: Neighbors,
    xy: XY,
) -> DInfFlowResult:
    """Compute a first D-infinity-style flow direction on a polygonal DGGS.

    Consecutive neighbors around the cell form triangular facets. A plane is fit
    through the center and each neighbor pair. If the plane's steepest downslope
    vector lies inside that facet and both bounding neighbors are lower, flow is
    split between them according to angular position. Otherwise the facet reduces
    to its steepest valid downslope edge. The globally steepest candidate wins.

    Missing neighbors in ``elevation`` are treated as no-data/domain boundaries.
    """
    z0 = float(elevation[cell])
    ring = ordered_neighbors(cell, neighbors, xy)
    if not ring:
        return DInfFlowResult(cell, None, 0.0, None, 0.0, None, 0.0)

    best_slope = 0.0
    best_direction: float | None = None
    best_r1: Cell | None = None
    best_f1 = 0.0
    best_r2: Cell | None = None
    best_f2 = 0.0
    eps = 1e-12

    # Edge candidates ensure sensible routing at domain boundaries and when a
    # facet's unconstrained gradient points outside the triangular wedge.
    for neighbor in ring:
        edge = _edge_candidate(neighbor, z0, elevation, xy, cell)
        if edge is not None and edge[0] > best_slope:
            best_slope, best_direction = edge
            best_r1, best_f1 = neighbor, 1.0
            best_r2, best_f2 = None, 0.0

    if len(ring) < 2:
        return DInfFlowResult(
            cell, best_direction, best_slope, best_r1, best_f1, best_r2, best_f2
        )

    for i, n1 in enumerate(ring):
        n2 = ring[(i + 1) % len(ring)]
        if n1 not in elevation or n2 not in elevation:
            continue

        x1, y1 = xy(n1, cell)
        x2, y2 = xy(n2, cell)
        det = x1 * y2 - x2 * y1
        if abs(det) <= eps:
            continue

        dz1 = float(elevation[n1]) - z0
        dz2 = float(elevation[n2]) - z0

        # z = z0 + a*x + b*y on this facet.
        a = (dz1 * y2 - dz2 * y1) / det
        b = (x1 * dz2 - x2 * dz1) / det
        slope = math.hypot(a, b)
        if slope <= best_slope + eps:
            continue

        direction = _angle(-a, -b)
        angle1 = _angle(x1, y1)
        angle2 = _angle(x2, y2)
        wedge = (angle2 - angle1) % (2.0 * math.pi)
        offset = (direction - angle1) % (2.0 * math.pi)

        # H3 neighbor wedges are small (< pi). The check is generic for other
        # polygonal cells as long as cyclic neighbors describe convex local facets.
        inside = wedge > eps and wedge < math.pi and offset <= wedge + eps
        both_lower = dz1 < 0.0 and dz2 < 0.0
        if not (inside and both_lower):
            continue

        f2 = min(1.0, max(0.0, offset / wedge))
        f1 = 1.0 - f2
        best_slope = slope
        best_direction = direction

        # Avoid storing a numerically insignificant second receiver.
        if f1 <= 1e-10:
            best_r1, best_f1 = n2, 1.0
            best_r2, best_f2 = None, 0.0
        elif f2 <= 1e-10:
            best_r1, best_f1 = n1, 1.0
            best_r2, best_f2 = None, 0.0
        else:
            best_r1, best_f1 = n1, f1
            best_r2, best_f2 = n2, f2

    return DInfFlowResult(
        cell, best_direction, best_slope, best_r1, best_f1, best_r2, best_f2
    )


def compute_dinf_flow_directions(
    elevation: Mapping[Cell, float],
    neighbors: Neighbors,
    xy: XY,
    *,
    workers: int = 1,
    chunksize: int = 256,
    progress: bool = False,
) -> dict[Cell, DInfFlowResult]:
    """Compute independent D-infinity-style directions for every DEM cell.

    ``workers > 1`` evaluates independent source cells concurrently using the
    shared-memory thread backend.
    """
    cells = tuple(elevation)
    func = partial(dinf_flow_direction, elevation=elevation, neighbors=neighbors, xy=xy)
    results = map_independent(func, cells, workers=workers, chunksize=chunksize, progress=progress, progress_desc="D-infinity routing")
    return dict(zip(cells, results))
