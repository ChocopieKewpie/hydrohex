from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Hashable, Mapping, Sequence, TypeVar

from .graph import WeightedFlowGraph
from .parallel import resolve_workers

Cell = TypeVar("Cell", bound=Hashable)


class FlowCycleError(ValueError):
    """Raised when a flow graph cannot be topologically accumulated."""


@dataclass(frozen=True, slots=True)
class AccumulationStats:
    """Execution diagnostics for a topological accumulation traversal."""

    fronts: int
    max_front_width: int
    parallel_fronts: int
    processed_cells: int


@dataclass(frozen=True, slots=True)
class AccumulationResult:
    """Accumulated local contribution and conservative edge-contamination flags."""

    values: Mapping[Hashable, float]
    edge_contaminated: Mapping[Hashable, bool]
    stats: AccumulationStats | None = None

    def __getitem__(self, cell: Hashable) -> float:
        return self.values[cell]


def boundary_cells(
    cells: Mapping[Cell, object] | set[Cell] | tuple[Cell, ...] | list[Cell],
    neighbors: Callable[[Cell], list[Cell] | tuple[Cell, ...]],
) -> set[Cell]:
    """Return domain cells touching at least one neighbor outside the supplied domain."""
    domain = set(cells)
    return {
        cell
        for cell in domain
        if any(neighbor not in domain for neighbor in neighbors(cell))
    }


def _front_chunks(front: Sequence[Hashable], workers: int) -> list[tuple[Hashable, ...]]:
    """Split one topological front into at most ``workers`` balanced chunks."""
    if not front:
        return []
    chunk_size = max(1, math.ceil(len(front) / workers))
    return [tuple(front[i : i + chunk_size]) for i in range(0, len(front), chunk_size)]


def _process_front_chunk(
    chunk: Sequence[Hashable],
    graph: WeightedFlowGraph,
    values: Mapping[Hashable, float],
    contaminated: Mapping[Hashable, bool],
) -> tuple[dict[Hashable, float], set[Hashable], dict[Hashable, int]]:
    """Build thread-local receiver updates for one independent topological-front chunk."""
    additions: dict[Hashable, float] = {}
    contaminated_receivers: set[Hashable] = set()
    indegree_decrements: dict[Hashable, int] = {}

    for cell in chunk:
        source_value = values[cell]
        source_contaminated = contaminated[cell]
        for edge in graph.outgoing[cell]:
            receiver = edge.receiver
            additions[receiver] = additions.get(receiver, 0.0) + source_value * edge.fraction
            indegree_decrements[receiver] = indegree_decrements.get(receiver, 0) + 1
            if source_contaminated:
                contaminated_receivers.add(receiver)

    return additions, contaminated_receivers, indegree_decrements


def accumulate(
    graph: WeightedFlowGraph,
    local_contribution: Mapping[Cell, float] | None = None,
    *,
    edge_contaminated_sources: set[Cell] | None = None,
    workers: int = 1,
    parallel_min_front_size: int = 256,
) -> AccumulationResult:
    """Accumulate a weighted directed acyclic flow graph in O(V + E).

    The traversal is performed as topological *fronts*. Every cell in a front has
    all upstream dependencies satisfied, so cells within that front can be
    processed independently. With ``workers > 1`` sufficiently wide fronts are
    divided among worker threads. Workers produce thread-local receiver updates;
    updates are reduced on the main thread before the next front begins, avoiding
    concurrent writes and preserving deterministic dependency ordering.

    With ``local_contribution=None`` each cell contributes 1.0, giving an
    equivalent contributing-cell count. Supplying H3 cell areas instead gives
    physical contributing area. D-infinity fractions are applied naturally.

    ``edge_contaminated_sources`` marks cells that touch an incomplete/no-data
    boundary. Contamination is propagated downstream along positive flow edges.

    ``parallel_min_front_size`` prevents thread scheduling overhead on narrow
    fronts. The threaded implementation is an experimental bridge to the planned
    indexed NumPy backend; speedup depends on graph shape and Python runtime.
    """
    graph.validate()
    n_workers = resolve_workers(workers)
    if parallel_min_front_size < 1:
        raise ValueError("parallel_min_front_size must be >= 1")

    cells = graph.cells
    cell_set = set(cells)

    if local_contribution is None:
        values: dict[Hashable, float] = {cell: 1.0 for cell in cells}
    else:
        missing = cell_set.difference(local_contribution)
        if missing:
            sample = next(iter(missing))
            raise ValueError(f"Missing local contribution for cell {sample!r}")
        values = {cell: float(local_contribution[cell]) for cell in cells}

    sources = edge_contaminated_sources or set()
    unknown_sources = set(sources).difference(cell_set)
    if unknown_sources:
        sample = next(iter(unknown_sources))
        raise ValueError(f"Unknown contaminated source cell {sample!r}")
    contaminated: dict[Hashable, bool] = {cell: cell in sources for cell in cells}

    indegree: dict[Hashable, int] = {cell: 0 for cell in cells}
    for source in cells:
        for edge in graph.outgoing[source]:
            indegree[edge.receiver] += 1

    front: list[Hashable] = [cell for cell in cells if indegree[cell] == 0]
    processed = 0
    front_count = 0
    max_front_width = 0
    parallel_fronts = 0

    executor: ThreadPoolExecutor | None = None
    if n_workers > 1:
        executor = ThreadPoolExecutor(
            max_workers=n_workers,
            thread_name_prefix="hydrohex-accum",
        )

    try:
        while front:
            front_count += 1
            max_front_width = max(max_front_width, len(front))
            processed += len(front)

            use_parallel = (
                executor is not None
                and len(front) >= parallel_min_front_size
                and len(front) > 1
            )

            if use_parallel:
                parallel_fronts += 1
                chunks = _front_chunks(front, n_workers)
                futures = [
                    executor.submit(
                        _process_front_chunk,
                        chunk,
                        graph,
                        values,
                        contaminated,
                    )
                    for chunk in chunks
                ]
                updates = [future.result() for future in futures]
            else:
                updates = [
                    _process_front_chunk(front, graph, values, contaminated)
                ]

            next_front: list[Hashable] = []
            for additions, contaminated_receivers, decrements in updates:
                for receiver, addition in additions.items():
                    values[receiver] += addition
                for receiver in contaminated_receivers:
                    contaminated[receiver] = True
                for receiver, decrement in decrements.items():
                    indegree[receiver] -= decrement
                    if indegree[receiver] == 0:
                        next_front.append(receiver)
                    elif indegree[receiver] < 0:
                        raise RuntimeError(
                            f"Negative indegree while accumulating receiver {receiver!r}"
                        )

            front = next_front
    finally:
        if executor is not None:
            executor.shutdown(wait=True)

    if processed != len(cells):
        cyclic = [cell for cell in cells if indegree[cell] > 0]
        preview = ", ".join(repr(cell) for cell in cyclic[:5])
        raise FlowCycleError(
            f"Flow graph contains a directed cycle; {len(cyclic)} cell(s) remain: {preview}"
        )

    return AccumulationResult(
        values=values,
        edge_contaminated=contaminated,
        stats=AccumulationStats(
            fronts=front_count,
            max_front_width=max_front_width,
            parallel_fronts=parallel_fronts,
            processed_cells=processed,
        ),
    )


@dataclass(frozen=True, slots=True)
class FlowAccumulation:
    """Convenience pair of equivalent-cell and physical-area accumulations."""

    cells: AccumulationResult
    area_m2: AccumulationResult


def accumulate_flow(
    graph: WeightedFlowGraph,
    cell_area_m2: Mapping[Cell, float],
    *,
    edge_contaminated_sources: set[Cell] | None = None,
    workers: int = 1,
    parallel_min_front_size: int = 256,
) -> FlowAccumulation:
    """Compute equivalent contributing-cell count and physical contributing area.

    Both traversals use the same topological-front parallel strategy. ``workers``
    therefore controls accumulation as well as the independent routing stages in
    the high-level pipeline.
    """
    return FlowAccumulation(
        cells=accumulate(
            graph,
            edge_contaminated_sources=edge_contaminated_sources,
            workers=workers,
            parallel_min_front_size=parallel_min_front_size,
        ),
        area_m2=accumulate(
            graph,
            cell_area_m2,
            edge_contaminated_sources=edge_contaminated_sources,
            workers=workers,
            parallel_min_front_size=parallel_min_front_size,
        ),
    )
