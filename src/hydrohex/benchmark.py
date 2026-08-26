from __future__ import annotations

import csv
import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Hashable, Mapping

from .core import FlowResult, compute_flow_directions
from .indexed import IndexedDGGSGrid, compute_d6_indexed
from .parallel import resolve_workers


@dataclass(frozen=True, slots=True)
class D6BenchmarkResult:
    """Timing and correctness summary for Python vs indexed D6 routing."""

    cells: int
    workers: int
    repeats: int
    warmup: int
    source: str
    python_times_s: tuple[float, ...]
    indexed_build_s: float
    indexed_times_s: tuple[float, ...]
    equivalent_receivers: bool

    @property
    def python_median_s(self) -> float:
        return float(statistics.median(self.python_times_s))

    @property
    def indexed_median_s(self) -> float:
        return float(statistics.median(self.indexed_times_s))

    @property
    def indexed_first_run_s(self) -> float:
        return self.indexed_build_s + self.indexed_median_s

    @property
    def routing_speedup(self) -> float:
        value = self.indexed_median_s
        return float("inf") if value <= 0.0 else self.python_median_s / value

    @property
    def first_run_speedup(self) -> float:
        value = self.indexed_first_run_s
        return float("inf") if value <= 0.0 else self.python_median_s / value

    def to_dict(self) -> dict[str, object]:
        return {
            "cells": self.cells,
            "workers": self.workers,
            "repeats": self.repeats,
            "warmup": self.warmup,
            "source": self.source,
            "python_times_s": list(self.python_times_s),
            "python_median_s": self.python_median_s,
            "indexed_build_s": self.indexed_build_s,
            "indexed_times_s": list(self.indexed_times_s),
            "indexed_median_s": self.indexed_median_s,
            "indexed_first_run_s": self.indexed_first_run_s,
            "routing_speedup": self.routing_speedup,
            "first_run_speedup": self.first_run_speedup,
            "equivalent_receivers": self.equivalent_receivers,
        }


def _receivers_match(
    python_result: Mapping[Hashable, FlowResult],
    indexed_result: Mapping[Hashable, FlowResult],
) -> bool:
    if python_result.keys() != indexed_result.keys():
        return False
    return all(
        python_result[cell].flow_to == indexed_result[cell].flow_to
        for cell in python_result
    )


def benchmark_d6_backends(
    elevation: Mapping[Hashable, float],
    neighbors: Callable[[Hashable], list[Hashable] | tuple[Hashable, ...]],
    distance: Callable[[Hashable, Hashable], float],
    latlng: Callable[[Hashable], tuple[float, float]],
    *,
    workers: int = 1,
    repeats: int = 3,
    warmup: int = 1,
    source: str = "in-memory DEM",
) -> D6BenchmarkResult:
    """Benchmark the legacy Python and indexed NumPy D6 implementations.

    The indexed topology is built once and reused for all indexed routing repeats.
    This deliberately reports both routing-only performance and the first-run cost
    that includes topology construction.
    """
    if not elevation:
        raise ValueError("benchmark elevation must not be empty")
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    if warmup < 0:
        raise ValueError("warmup must be >= 0")

    resolved_workers = resolve_workers(workers)

    for _ in range(warmup):
        compute_flow_directions(
            elevation,
            neighbors,
            distance,
            workers=resolved_workers,
            progress=False,
        )

    python_times: list[float] = []
    python_result: Mapping[Hashable, FlowResult] | None = None
    for _ in range(repeats):
        started = time.perf_counter()
        python_result = compute_flow_directions(
            elevation,
            neighbors,
            distance,
            workers=resolved_workers,
            progress=False,
        )
        python_times.append(time.perf_counter() - started)

    started = time.perf_counter()
    grid = IndexedDGGSGrid.build_geographic(
        elevation,
        neighbors,
        latlng,
        progress=False,
    )
    indexed_build_s = time.perf_counter() - started

    for _ in range(warmup):
        compute_d6_indexed(grid, workers=resolved_workers, progress=False)

    indexed_times: list[float] = []
    indexed_result: Mapping[Hashable, FlowResult] | None = None
    for _ in range(repeats):
        started = time.perf_counter()
        indexed_result = compute_d6_indexed(
            grid,
            workers=resolved_workers,
            progress=False,
        )
        indexed_times.append(time.perf_counter() - started)

    assert python_result is not None
    assert indexed_result is not None
    equivalent = _receivers_match(python_result, indexed_result)
    if not equivalent:
        raise AssertionError("Python and indexed D6 backends produced different receivers")

    return D6BenchmarkResult(
        cells=len(elevation),
        workers=resolved_workers,
        repeats=repeats,
        warmup=warmup,
        source=source,
        python_times_s=tuple(python_times),
        indexed_build_s=float(indexed_build_s),
        indexed_times_s=tuple(indexed_times),
        equivalent_receivers=equivalent,
    )


def write_benchmark_json(path: str | Path, result: D6BenchmarkResult) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_benchmark_csv(path: str | Path, result: D6BenchmarkResult) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = result.to_dict()
    row["python_times_s"] = ";".join(f"{value:.9f}" for value in result.python_times_s)
    row["indexed_times_s"] = ";".join(f"{value:.9f}" for value in result.indexed_times_s)
    path.write_text("", encoding="utf-8")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    return path


def format_benchmark(result: D6BenchmarkResult) -> str:
    return "\n".join(
        [
            "HydroHex D6 backend benchmark",
            f"source:                 {result.source}",
            f"cells:                  {result.cells:,}",
            f"workers:                {result.workers}",
            f"repeats / warmup:       {result.repeats} / {result.warmup}",
            f"legacy Python median:   {result.python_median_s:.6f} s",
            f"indexed topology build: {result.indexed_build_s:.6f} s",
            f"indexed routing median: {result.indexed_median_s:.6f} s",
            f"indexed first run:      {result.indexed_first_run_s:.6f} s",
            f"routing-only speedup:   {result.routing_speedup:.2f}x",
            f"first-run speedup:      {result.first_run_speedup:.2f}x",
            "receiver equivalence:   exact",
        ]
    )
