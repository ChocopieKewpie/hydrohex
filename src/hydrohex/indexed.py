from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Hashable, Mapping, TypeVar

import numpy as np

from .core import FlowResult
from .parallel import resolve_workers
from .progress import progress_bar

Cell = TypeVar("Cell", bound=Hashable)
Neighbors = Callable[[Cell], list[Cell] | tuple[Cell, ...]]
Distance = Callable[[Cell, Cell], float]


@dataclass(slots=True)
class IndexedDGGSGrid:
    """Compact numeric topology for a fixed DGGS DEM domain.

    ``neighbor_index`` stores row indices rather than cell identifiers. ``-1``
    represents a neighbor outside the supplied DEM or an unused slot. Building
    this structure is intentionally separated from routing so the topology can be
    reused by additional numeric kernels later (D∞, smoothing, accumulation).
    """

    cells: tuple[Hashable, ...]
    elevation: np.ndarray
    neighbor_index: np.ndarray
    neighbor_distance: np.ndarray
    boundary_mask: np.ndarray
    index: dict[Hashable, int]

    @classmethod
    def build(
        cls,
        elevation: Mapping[Cell, float],
        neighbors: Neighbors,
        distance: Distance,
        *,
        max_neighbors: int = 6,
        progress: bool = False,
    ) -> "IndexedDGGSGrid":
        if max_neighbors < 1:
            raise ValueError("max_neighbors must be >= 1")
        cells = tuple(elevation)
        n = len(cells)
        index = {cell: i for i, cell in enumerate(cells)}
        z = np.fromiter((float(elevation[cell]) for cell in cells), dtype=np.float64, count=n)
        neighbor_index = np.full((n, max_neighbors), -1, dtype=np.int32)
        neighbor_distance = np.full((n, max_neighbors), np.inf, dtype=np.float64)
        boundary_mask = np.zeros(n, dtype=bool)

        with progress_bar(total=n, desc="Building indexed topology", enabled=progress) as bar:
            for i, cell in enumerate(cells):
                ring = tuple(neighbors(cell))
                if len(ring) > max_neighbors:
                    raise ValueError(
                        f"Cell {cell!r} has {len(ring)} neighbors; max_neighbors={max_neighbors}"
                    )
                if any(neighbor not in index for neighbor in ring):
                    boundary_mask[i] = True
                slot = 0
                for neighbor in ring:
                    j = index.get(neighbor)
                    if j is None:
                        continue
                    d = float(distance(cell, neighbor))
                    if d <= 0.0:
                        raise ValueError(
                            f"Distance must be > 0 for edge {cell!r} -> {neighbor!r}"
                        )
                    neighbor_index[i, slot] = j
                    neighbor_distance[i, slot] = d
                    slot += 1
                bar.update(1)

        return cls(
            cells=cells,
            elevation=z,
            neighbor_index=neighbor_index,
            neighbor_distance=neighbor_distance,
            boundary_mask=boundary_mask,
            index=index,
        )


    @classmethod
    def build_geographic(
        cls,
        elevation: Mapping[Cell, float],
        neighbors: Neighbors,
        latlng: Callable[[Cell], tuple[float, float]],
        *,
        max_neighbors: int = 6,
        earth_radius_m: float = 6_371_008.8,
        progress: bool = False,
    ) -> "IndexedDGGSGrid":
        """Build indexed topology and vectorize center-distance calculation.

        Each cell centre is converted to latitude/longitude once. Great-circle
        distances for all in-domain neighbor edges are then calculated together
        with NumPy, avoiding repeated H3 center/distance calls per edge.
        """
        if max_neighbors < 1:
            raise ValueError("max_neighbors must be >= 1")
        cells = tuple(elevation)
        n = len(cells)
        index = {cell: i for i, cell in enumerate(cells)}
        z = np.fromiter((float(elevation[cell]) for cell in cells), dtype=np.float64, count=n)
        neighbor_index = np.full((n, max_neighbors), -1, dtype=np.int32)
        boundary_mask = np.zeros(n, dtype=bool)
        lat_rad = np.empty(n, dtype=np.float64)
        lon_rad = np.empty(n, dtype=np.float64)

        with progress_bar(total=n, desc="Building indexed H3 topology", enabled=progress) as bar:
            for i, cell in enumerate(cells):
                lat, lon = latlng(cell)
                lat_rad[i] = np.deg2rad(float(lat))
                lon_rad[i] = np.deg2rad(float(lon))
                ring = tuple(neighbors(cell))
                if len(ring) > max_neighbors:
                    raise ValueError(
                        f"Cell {cell!r} has {len(ring)} neighbors; max_neighbors={max_neighbors}"
                    )
                if any(neighbor not in index for neighbor in ring):
                    boundary_mask[i] = True
                slot = 0
                for neighbor in ring:
                    j = index.get(neighbor)
                    if j is None:
                        continue
                    neighbor_index[i, slot] = j
                    slot += 1
                bar.update(1)

        missing = n
        gather = np.where(neighbor_index >= 0, neighbor_index, missing)
        lat_ext = np.concatenate([lat_rad, np.array([np.nan])])
        lon_ext = np.concatenate([lon_rad, np.array([np.nan])])
        lat2 = lat_ext[gather]
        lon2 = lon_ext[gather]
        lat1 = lat_rad[:, None]
        lon1 = lon_rad[:, None]
        dlat = lat2 - lat1
        dlon = (lon2 - lon1 + np.pi) % (2.0 * np.pi) - np.pi
        a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
        a = np.clip(a, 0.0, 1.0)
        neighbor_distance = 2.0 * earth_radius_m * np.arcsin(np.sqrt(a))
        neighbor_distance = np.where(neighbor_index >= 0, neighbor_distance, np.inf)

        return cls(
            cells=cells,
            elevation=z,
            neighbor_index=neighbor_index,
            neighbor_distance=neighbor_distance,
            boundary_mask=boundary_mask,
            index=index,
        )

    @property
    def size(self) -> int:
        return len(self.cells)

    @property
    def boundary_cells(self) -> set[Hashable]:
        return {self.cells[i] for i in np.flatnonzero(self.boundary_mask)}


def _d6_chunk(
    grid: IndexedDGGSGrid,
    start: int,
    stop: int,
    z_with_missing: np.ndarray,
) -> tuple[int, int, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    idx = grid.neighbor_index[start:stop]
    n = grid.size
    gather_idx = np.where(idx >= 0, idx, n)
    neighbor_z = z_with_missing[gather_idx]
    source_z = grid.elevation[start:stop, None]
    drop = source_z - neighbor_z
    valid = (idx >= 0) & (drop > 0.0)
    slope = np.where(valid, drop / grid.neighbor_distance[start:stop], -np.inf)
    best_slot = np.argmax(slope, axis=1)
    row = np.arange(stop - start)
    best_slope = slope[row, best_slot]
    routed = np.isfinite(best_slope) & (best_slope > 0.0)

    chunk_receivers = np.full(stop - start, -1, dtype=np.int32)
    chunk_drops = np.zeros(stop - start, dtype=np.float64)
    chunk_distances = np.zeros(stop - start, dtype=np.float64)
    chunk_slopes = np.zeros(stop - start, dtype=np.float64)
    local_rows = row[routed]
    slots = best_slot[routed]
    chunk_receivers[routed] = idx[local_rows, slots]
    chunk_drops[routed] = drop[local_rows, slots]
    chunk_distances[routed] = grid.neighbor_distance[start:stop][local_rows, slots]
    chunk_slopes[routed] = best_slope[routed]
    return start, stop, chunk_receivers, chunk_drops, chunk_distances, chunk_slopes


def compute_d6_indexed(
    grid: IndexedDGGSGrid,
    *,
    workers: int = 1,
    chunk_size: int = 50_000,
    progress: bool = False,
) -> dict[Hashable, FlowResult]:
    """Vectorized and optionally threaded D6 routing on indexed topology.

    NumPy performs the slope kernel for blocks of source cells. With multiple
    workers, independent blocks run concurrently and only write their own output
    slices, so no routing locks or atomics are required.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")
    n_workers = resolve_workers(workers)
    n = grid.size
    receivers = np.full(n, -1, dtype=np.int32)
    drops = np.zeros(n, dtype=np.float64)
    distances = np.zeros(n, dtype=np.float64)
    slopes = np.zeros(n, dtype=np.float64)

    z_with_missing = np.empty(n + 1, dtype=np.float64)
    z_with_missing[:n] = grid.elevation
    z_with_missing[n] = np.nan
    chunks = [(start, min(n, start + chunk_size)) for start in range(0, n, chunk_size)]

    def apply(result):
        start, stop, recv, drop, dist, slope = result
        receivers[start:stop] = recv
        drops[start:stop] = drop
        distances[start:stop] = dist
        slopes[start:stop] = slope
        return stop - start

    with progress_bar(total=n, desc="D6 indexed routing", enabled=progress) as bar:
        if n_workers == 1 or len(chunks) <= 1:
            for start, stop in chunks:
                bar.update(apply(_d6_chunk(grid, start, stop, z_with_missing)))
        else:
            with ThreadPoolExecutor(
                max_workers=n_workers, thread_name_prefix="hydrohex-d6-indexed"
            ) as pool:
                futures = [
                    pool.submit(_d6_chunk, grid, start, stop, z_with_missing)
                    for start, stop in chunks
                ]
                for future in futures:
                    bar.update(apply(future.result()))

    results: dict[Hashable, FlowResult] = {}
    with progress_bar(total=n, desc="Materializing D6 results", enabled=progress) as bar:
        for i, cell in enumerate(grid.cells):
            receiver_i = int(receivers[i])
            receiver = None if receiver_i < 0 else grid.cells[receiver_i]
            results[cell] = FlowResult(
                cell=cell,
                flow_to=receiver,
                drop=float(drops[i]),
                distance=float(distances[i]),
                slope=float(slopes[i]),
            )
            bar.update(1)
    return results
