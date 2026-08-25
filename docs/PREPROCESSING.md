# Terrain preprocessing

The preprocessing tools operate on a mapping of `cell_id -> elevation` and DGGS adjacency callbacks. H3 is only required by the H3 adapter/CLI.

## Non-destructive result model

Every terrain operation returns `TerrainResult`:

```python
TerrainResult(
    elevation=...,       # transformed elevations
    delta=...,           # transformed - input
    modified_cells=...,  # cells whose elevation changed
    diagnostics=...,     # fill_depth_m / breach_depth_m etc.
    metadata=...,
)
```

This keeps the raw DEM available for audit and makes QGIS before/after comparison straightforward.

## Smoothing

`hydrohex.terrain.smooth_dem` supports:

- `mean`
- `median`
- `bilateral`

Bilateral smoothing combines center-to-center distance and elevation similarity. It is the preferred first filter when preserving sharp terrain features matters.

Each iteration is independent per output cell and can use `workers > 1`.

## Pit and flat diagnostics

- `find_pits`: strict local minima by default; domain-boundary cells are excluded.
- `find_flats`: cells sharing elevation with one or more in-domain neighbors.

A future flat-resolution tool should assign drainage gradients through connected flat regions rather than treating flats only diagnostically.

## Priority-Flood

`priority_flood_fill` seeds the priority queue from domain-boundary cells (or explicit outlets). Unvisited neighbors are raised to the current spill elevation. With `min_slope > 0`, cells are raised slightly more with distance so flow can descend toward the processed outlet path.

Priority-Flood is intentionally serial in this reference implementation because queue order defines the flood traversal.

## Breaching

`breach_depressions` currently:

1. Finds strict local pits.
2. Searches the DGGS graph toward lower terrain or the domain boundary.
3. Uses terrain above the pit floor as an excavation-cost proxy.
4. Reconstructs the least-cost path.
5. Carves a monotonically descending profile.
6. Rejects a breach when it exceeds `max_breach_depth_m`.

This is a useful reference implementation, but it does not yet model excavation volume from full cell geometry or compare all possible depression-spill alternatives as sophisticated production breaching packages do.

## Hybrid

`condition_dem(..., method="hybrid")`:

1. Runs a zero-slope Priority-Flood preview.
2. Finds pits whose preview fill depth exceeds `max_fill_depth_m`.
3. Attempts to breach those deep pits.
4. Runs a final Priority-Flood to remove remaining depressions.

This gives the toolbox a practical fill-or-breach workflow while preserving explicit diagnostics for how the surface changed.
