"""DGGS-native terrain diagnostics and preprocessing tools."""

from .base import TerrainResult
from .breach import breach_depressions
from .condition import condition_dem
from .depressions import find_flats, find_pits
from .fill import priority_flood_fill
from .smooth import smooth_dem

__all__ = [
    "TerrainResult",
    "find_pits",
    "find_flats",
    "smooth_dem",
    "priority_flood_fill",
    "breach_depressions",
    "condition_dem",
]
