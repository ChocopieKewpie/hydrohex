"""DGGS terrain preprocessing, flow-direction, graph, and accumulation toolbox."""

from .accumulation import (
    AccumulationResult,
    AccumulationStats,
    FlowAccumulation,
    FlowCycleError,
    accumulate,
    accumulate_flow,
    boundary_cells,
)
from .core import FlowResult, compute_flow_directions, flow_direction
from .dinf import DInfFlowResult, compute_dinf_flow_directions, dinf_flow_direction
from .graph import FlowEdge, WeightedFlowGraph, graph_from_d6, graph_from_dinf
from .indexed import IndexedDGGSGrid, compute_d6_indexed
from .benchmark import D6BenchmarkResult, benchmark_d6_backends
from .neutral import NeutralTerrainParameters, generate_neutral_surface
from .terrain import (
    TerrainResult,
    breach_depressions,
    condition_dem,
    find_flats,
    find_pits,
    priority_flood_fill,
    smooth_dem,
)

__version__ = "0.2.0"

__all__ = [
    "__version__",
    "FlowResult",
    "flow_direction",
    "compute_flow_directions",
    "DInfFlowResult",
    "dinf_flow_direction",
    "compute_dinf_flow_directions",
    "FlowEdge",
    "WeightedFlowGraph",
    "graph_from_d6",
    "graph_from_dinf",
    "IndexedDGGSGrid",
    "compute_d6_indexed",
    "D6BenchmarkResult",
    "benchmark_d6_backends",
    "AccumulationResult",
    "AccumulationStats",
    "FlowAccumulation",
    "FlowCycleError",
    "accumulate",
    "accumulate_flow",
    "boundary_cells",
    "NeutralTerrainParameters",
    "generate_neutral_surface",
    "TerrainResult",
    "find_pits",
    "find_flats",
    "smooth_dem",
    "priority_flood_fill",
    "breach_depressions",
    "condition_dem",
]
