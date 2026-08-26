from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Sized
from typing import Callable, Iterable, TypeVar

from .progress import progress_iter

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
    progress: bool = False,
    progress_desc: str = "Processing cells",
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
    total = len(items) if isinstance(items, Sized) else None
    if n_workers == 1:
        iterator = (func(item) for item in items)
        return list(progress_iter(iterator, total=total, desc=progress_desc, enabled=progress))
    with ThreadPoolExecutor(max_workers=n_workers, thread_name_prefix="hydrohex") as pool:
        iterator = pool.map(func, items, chunksize=chunksize)
        return list(progress_iter(iterator, total=total, desc=progress_desc, enabled=progress))
