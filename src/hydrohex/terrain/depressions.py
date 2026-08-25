from __future__ import annotations

from typing import Callable, Hashable, Mapping, TypeVar

Cell = TypeVar("Cell", bound=Hashable)
Neighbors = Callable[[Cell], list[Cell] | tuple[Cell, ...]]


def find_pits(
    elevation: Mapping[Cell, float],
    neighbors: Neighbors,
    *,
    include_flats: bool = False,
) -> set[Cell]:
    """Find local minima within the supplied domain.

    Missing neighbors are treated as domain boundaries, so boundary cells are not
    classified as pits. With ``include_flats=False`` a pit must be strictly lower
    than every in-domain neighbor. The flat-aware mode reports cells that have no
    lower in-domain neighbor and at least one strictly higher neighbor.
    """
    domain = set(elevation)
    pits: set[Cell] = set()
    for cell in elevation:
        ring = neighbors(cell)
        if any(n not in domain for n in ring):
            continue
        z = float(elevation[cell])
        nz = [float(elevation[n]) for n in ring if n in domain]
        if not nz:
            continue
        if include_flats:
            if all(v >= z for v in nz) and any(v > z for v in nz):
                pits.add(cell)
        elif all(v > z for v in nz):
            pits.add(cell)
    return pits


def find_flats(
    elevation: Mapping[Cell, float],
    neighbors: Neighbors,
    *,
    tolerance: float = 1e-9,
) -> set[Cell]:
    """Return cells sharing elevation with at least one in-domain neighbor."""
    if tolerance < 0:
        raise ValueError("tolerance must be >= 0")
    domain = set(elevation)
    out: set[Cell] = set()
    for cell, z in elevation.items():
        if any(
            n in domain and abs(float(elevation[n]) - float(z)) <= tolerance
            for n in neighbors(cell)
        ):
            out.add(cell)
    return out
