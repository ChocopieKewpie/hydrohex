from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable, Iterable, Mapping, TypeVar

from .core import FlowResult
from .dinf import DInfFlowResult

Cell = TypeVar("Cell", bound=Hashable)


@dataclass(frozen=True, slots=True)
class FlowEdge:
    """One weighted directed edge in a DGGS flow graph."""

    source: Hashable
    receiver: Hashable
    fraction: float


@dataclass(frozen=True, slots=True)
class WeightedFlowGraph:
    """Sparse weighted flow graph shared by D6, D-infinity, and future methods.

    ``outgoing[cell]`` contains zero or more downstream edges. For a routed cell,
    positive edge fractions should sum to one. A cell with no outgoing edges is a
    sink/outlet within the supplied domain.
    """

    cells: tuple[Hashable, ...]
    outgoing: Mapping[Hashable, tuple[FlowEdge, ...]]

    @classmethod
    def from_edges(
        cls,
        cells: Iterable[Cell],
        edges: Iterable[FlowEdge],
        *,
        validate: bool = True,
    ) -> "WeightedFlowGraph":
        ordered_cells = tuple(cells)
        cell_set = set(ordered_cells)
        outgoing: dict[Hashable, list[FlowEdge]] = {cell: [] for cell in ordered_cells}

        for edge in edges:
            if edge.source not in cell_set:
                raise ValueError(f"Unknown edge source {edge.source!r}")
            if edge.receiver not in cell_set:
                raise ValueError(f"Unknown edge receiver {edge.receiver!r}")
            if edge.fraction <= 0.0:
                raise ValueError("Flow-edge fractions must be > 0")
            outgoing[edge.source].append(edge)

        frozen = {cell: tuple(items) for cell, items in outgoing.items()}
        graph = cls(ordered_cells, frozen)
        if validate:
            graph.validate()
        return graph

    def validate(self, *, tolerance: float = 1e-9) -> None:
        cell_set = set(self.cells)
        if len(cell_set) != len(self.cells):
            raise ValueError("Flow graph contains duplicate cells")
        if set(self.outgoing) != cell_set:
            raise ValueError("Flow graph outgoing mapping must contain every cell exactly once")

        for cell in self.cells:
            edges = self.outgoing[cell]
            if not edges:
                continue
            total = 0.0
            receivers: set[Hashable] = set()
            for edge in edges:
                if edge.source != cell:
                    raise ValueError(f"Outgoing edge source mismatch for {cell!r}")
                if edge.receiver not in cell_set:
                    raise ValueError(f"Unknown receiver {edge.receiver!r}")
                if edge.receiver == cell:
                    raise ValueError(f"Self-loop at {cell!r}")
                if edge.fraction <= 0.0:
                    raise ValueError("Flow-edge fractions must be > 0")
                if edge.receiver in receivers:
                    raise ValueError(f"Duplicate receiver {edge.receiver!r} from {cell!r}")
                receivers.add(edge.receiver)
                total += edge.fraction
            if abs(total - 1.0) > tolerance:
                raise ValueError(
                    f"Outgoing fractions for {cell!r} sum to {total}, expected 1"
                )


def graph_from_d6(results: Mapping[Cell, FlowResult]) -> WeightedFlowGraph:
    """Convert D6 results into a weighted graph (one edge with fraction 1)."""
    edges = [
        FlowEdge(cell, result.flow_to, 1.0)
        for cell, result in results.items()
        if result.flow_to is not None
    ]
    return WeightedFlowGraph.from_edges(results.keys(), edges)


def graph_from_dinf(results: Mapping[Cell, DInfFlowResult]) -> WeightedFlowGraph:
    """Convert D-infinity results into the same weighted-edge representation."""
    edges = [
        FlowEdge(cell, receiver, fraction)
        for cell, result in results.items()
        for receiver, fraction in result.receivers
    ]
    return WeightedFlowGraph.from_edges(results.keys(), edges)
