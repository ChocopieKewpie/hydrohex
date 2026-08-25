from __future__ import annotations

import argparse
from pathlib import Path

import h3

from .accumulation import accumulate_flow, boundary_cells
from .core import compute_flow_directions
from .datasets import DEFAULT_LAT, DEFAULT_LNG, DEFAULT_RESOLUTION, GENERATORS, equivalent_disk_radius
from .dinf import compute_dinf_flow_directions
from .graph import graph_from_d6, graph_from_dinf
from .h3_grid import cell_area_m2, distance_m, local_xy_m, neighbors
from .qgis import export_flow_geopackage


def _route_and_export(
    elevation: dict[str, float],
    path: Path,
    areas: dict[str, float],
    contaminated_sources: set[str],
    *,
    workers: int = 1,
) -> Path:
    d6 = compute_flow_directions(elevation, neighbors, distance_m, workers=workers)
    dinf = compute_dinf_flow_directions(elevation, neighbors, local_xy_m, workers=workers)
    d6_accum = accumulate_flow(
        graph_from_d6(d6),
        areas,
        edge_contaminated_sources=contaminated_sources,
        workers=workers,
    )
    dinf_accum = accumulate_flow(
        graph_from_dinf(dinf),
        areas,
        edge_contaminated_sources=contaminated_sources,
        workers=workers,
    )
    return export_flow_geopackage(
        elevation,
        d6,
        path,
        dinf_results=dinf,
        d6_accumulation=d6_accum,
        dinf_accumulation=dinf_accum,
    )


def generate_qgis_suite(
    output_dir: Path,
    lat: float = DEFAULT_LAT,
    lng: float = DEFAULT_LNG,
    resolution: int = DEFAULT_RESOLUTION,
    radius: int | None = None,
    *,
    workers: int = 1,
) -> list[Path]:
    """Generate deterministic analytic DEMs with D6, D-infinity and accumulation layers."""
    if radius is None:
        radius = equivalent_disk_radius(resolution)
    origin = h3.latlng_to_cell(lat, lng, resolution)
    cells = sorted(h3.grid_disk(origin, radius))
    output_dir.mkdir(parents=True, exist_ok=True)

    areas = {cell: cell_area_m2(cell) for cell in cells}
    contaminated_sources = boundary_cells(set(cells), neighbors)

    outputs: list[Path] = []
    for name, generator in GENERATORS.items():
        path = output_dir / f"h3_r{resolution}_{name}.gpkg"
        outputs.append(
            _route_and_export(
                generator(cells, origin),
                path,
                areas,
                contaminated_sources,
                workers=workers,
            )
        )
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate QGIS-ready deterministic analytic H3 D6/D-infinity datasets."
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data/generated"))
    parser.add_argument("--lat", type=float, default=DEFAULT_LAT)
    parser.add_argument("--lng", type=float, default=DEFAULT_LNG)
    parser.add_argument("--resolution", type=int, default=DEFAULT_RESOLUTION)
    parser.add_argument(
        "--radius",
        type=int,
        default=None,
        help="Grid radius. Defaults to a value matching the original res-8/radius-4 footprint.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Worker threads for routing and wide accumulation fronts; 0 uses all CPUs",
    )
    args = parser.parse_args()
    for path in generate_qgis_suite(
        args.output_dir,
        args.lat,
        args.lng,
        args.resolution,
        args.radius,
        workers=args.workers,
    ):
        print(path)


if __name__ == "__main__":
    main()
