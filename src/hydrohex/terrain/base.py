from __future__ import annotations

from dataclasses import dataclass, field
from typing import Hashable, Mapping


@dataclass(frozen=True, slots=True)
class TerrainResult:
    """A non-destructive terrain transformation and per-cell diagnostics."""

    elevation: Mapping[Hashable, float]
    delta: Mapping[Hashable, float]
    modified_cells: frozenset[Hashable]
    diagnostics: Mapping[str, Mapping[Hashable, float | bool]] = field(default_factory=dict)
    metadata: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def from_elevation(
        cls,
        original: Mapping[Hashable, float],
        transformed: Mapping[Hashable, float],
        *,
        diagnostics: Mapping[str, Mapping[Hashable, float | bool]] | None = None,
        metadata: Mapping[str, object] | None = None,
        tolerance: float = 1e-12,
    ) -> "TerrainResult":
        if set(original) != set(transformed):
            raise ValueError("Terrain transformation must preserve the cell domain")
        delta = {cell: float(transformed[cell]) - float(original[cell]) for cell in original}
        modified = frozenset(cell for cell, dz in delta.items() if abs(dz) > tolerance)
        return cls(
            elevation={cell: float(transformed[cell]) for cell in original},
            delta=delta,
            modified_cells=modified,
            diagnostics={} if diagnostics is None else diagnostics,
            metadata={} if metadata is None else metadata,
        )
