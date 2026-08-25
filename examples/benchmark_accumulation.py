"""Small synthetic benchmark for topological-front accumulation.

Run from an installed/editable environment:

    python examples/benchmark_accumulation.py
"""
from __future__ import annotations

from time import perf_counter

from hydrohex.accumulation import accumulate
from hydrohex.graph import FlowEdge, WeightedFlowGraph


def make_wide_convergence(n_sources: int = 100_000) -> WeightedFlowGraph:
    sink = n_sources
    cells = tuple(range(n_sources + 1))
    edges = [FlowEdge(source, sink, 1.0) for source in range(n_sources)]
    return WeightedFlowGraph.from_edges(cells, edges)


def main() -> None:
    graph = make_wide_convergence()
    for workers in (1, 2, 4, 8):
        start = perf_counter()
        result = accumulate(graph, workers=workers)
        elapsed = perf_counter() - start
        print(
            f"workers={workers:>2}  elapsed={elapsed:.4f}s  "
            f"sink={result[100_000]:.1f}  stats={result.stats}"
        )


if __name__ == "__main__":
    main()
