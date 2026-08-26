from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from typing import Iterable, Iterator, TypeVar

T = TypeVar("T")


class _NullProgress:
    def update(self, n: int = 1) -> None:
        return None

    def set_postfix_str(self, text: str, refresh: bool = True) -> None:
        return None

    def close(self) -> None:
        return None


class _SimpleProgress:
    """Dependency-free terminal progress fallback used when tqdm is unavailable."""

    def __init__(self, total: int | None, desc: str, unit: str) -> None:
        self.total = total
        self.desc = desc
        self.unit = unit
        self.count = 0
        self.started = time.monotonic()
        self.last_draw = 0.0
        self.postfix = ""
        self._draw(force=True)

    def update(self, n: int = 1) -> None:
        self.count += n
        self._draw(force=self.total is not None and self.count >= self.total)

    def set_postfix_str(self, text: str, refresh: bool = True) -> None:
        self.postfix = text
        if refresh:
            self._draw(force=True)

    def _draw(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self.last_draw < 0.2:
            return
        elapsed = max(now - self.started, 1e-9)
        rate = self.count / elapsed
        if self.total is None:
            message = f"\r{self.desc}: {self.count:,} {self.unit} [{rate:,.0f} {self.unit}/s]"
        else:
            fraction = 0.0 if self.total <= 0 else min(1.0, self.count / self.total)
            width = 24
            filled = int(round(width * fraction))
            bar = "#" * filled + "-" * (width - filled)
            message = (
                f"\r{self.desc}: [{bar}] {fraction * 100:5.1f}% "
                f"{self.count:,}/{self.total:,} {self.unit} [{rate:,.0f} {self.unit}/s]"
            )
        if self.postfix:
            message += f" {self.postfix}"
        sys.stderr.write(message)
        sys.stderr.flush()
        self.last_draw = now

    def close(self) -> None:
        self._draw(force=True)
        sys.stderr.write("\n")
        sys.stderr.flush()


def _tqdm():
    try:
        from tqdm.auto import tqdm
    except ImportError:  # tqdm is an enhancement, not a hard dependency
        return None
    return tqdm


@contextmanager
def progress_bar(
    *,
    total: int | None,
    desc: str,
    enabled: bool = False,
    unit: str = "cell",
):
    """Create a CLI-friendly progress bar.

    ``tqdm`` is used when installed; otherwise HydroHex falls back to a compact
    dependency-free terminal bar. Progress is opt-in for Python API callers and
    enabled by default by the CLI.
    """
    if not enabled:
        bar = _NullProgress()
        yield bar
        return
    tqdm = _tqdm()
    if tqdm is None:
        bar = _SimpleProgress(total, desc, unit)
    else:
        bar = tqdm(
            total=total,
            desc=desc,
            unit=unit,
            dynamic_ncols=True,
            mininterval=0.1,
            smoothing=0.1,
        )
    try:
        yield bar
    finally:
        bar.close()


def progress_iter(
    iterable: Iterable[T],
    *,
    total: int | None,
    desc: str,
    enabled: bool = False,
    unit: str = "cell",
) -> Iterator[T]:
    """Yield an iterable while reporting progress when requested."""
    with progress_bar(total=total, desc=desc, enabled=enabled, unit=unit) as bar:
        for item in iterable:
            yield item
            bar.update(1)
