from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def resolve_workers(workers: int | None) -> int:
    """Resolve a user worker count; 0/None means all available logical CPUs."""
    if workers is None or workers == 0:
        return max(1, os.cpu_count() or 1)
    if workers < 0:
        raise ValueError("workers must be >= 0")
    return max(1, workers)


def map_independent(
    func: Callable[[T], R],
    items: Iterable[T],
    *,
    workers: int = 1,
    chunksize: int = 256,
) -> list[R]:
    """Map an independent cell-local operation, preserving input order.

    Threads deliberately share the in-memory DEM/topology and avoid serializing a
    very large elevation mapping. This is useful for H3 calls implemented in C and
    provides one stable concurrency API ahead of the planned NumPy backend.
    Dependency-constrained graph algorithms intentionally do not use this helper.
    """
    n_workers = resolve_workers(workers)
    if chunksize < 1:
        raise ValueError("chunksize must be >= 1")
    if n_workers == 1:
        return [func(item) for item in items]
    with ThreadPoolExecutor(max_workers=n_workers, thread_name_prefix="hydrohex") as pool:
        return list(pool.map(func, items, chunksize=chunksize))
