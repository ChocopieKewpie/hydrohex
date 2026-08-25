from __future__ import annotations

import math
from pathlib import Path
from typing import Hashable, Mapping

from .accumulation import FlowAccumulation
from .core import FlowResult
from .dinf import DInfFlowResult

EARTH_RADIUS_M = 6_371_008.8
ExtraFields = Mapping[str, Mapping[Hashable, object]]


def _geometry_imports():
    try:
        import geopandas as gpd
        from shapely.geometry import LineString, Point, Polygon
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "QGIS export requires GIS dependencies. Install with "
            "`python -m pip install -e '.[gis]'` or use environment.yml."
        ) from exc
    return gpd, LineString, Point, Polygon


def _h3_import():
    try:
        import h3
    except ImportError as exc:  # pragma: no cover
        raise ImportError("QGIS H3 export requires the `h3` package.") from exc
    return h3


def _polygon_from_latlng_boundary(boundary):
    _, _, _, Polygon = _geometry_imports()
    return Polygon([(lng, lat) for lat, lng in boundary])


def h3_cell_polygon(cell: str):
    h3 = _h3_import()
    return _polygon_from_latlng_boundary(h3.cell_to_boundary(cell))


def _add_extra(row: dict[str, object], cell: str, extra_cell_fields: ExtraFields | None) -> None:
    if extra_cell_fields is None:
        return
    for name, values in extra_cell_fields.items():
        row[name] = values.get(cell)


def build_cells_gdf(
    elevation: Mapping[str, float],
    flow_results: Mapping[str, FlowResult] | None = None,
    accumulation: FlowAccumulation | None = None,
    *,
    extra_cell_fields: ExtraFields | None = None,
):
    """Base polygon layer, optionally carrying D6 routing and preprocessing fields."""
    gpd, _, _, Polygon = _geometry_imports()
    h3 = _h3_import()
    rows = []
    for cell in sorted(elevation):
        result = None if flow_results is None else flow_results[cell]
        row: dict[str, object] = {
            "h3_id": cell,
            "elevation_m": float(elevation[cell]),
            "flow_to": None if result is None else result.flow_to,
            "drop_m": None if result is None else float(result.drop),
            "distance_m": None if result is None else float(result.distance),
            "slope": None if result is None else float(result.slope),
            "sink": None if result is None else result.flow_to is None,
            "accum_cells": None if accumulation is None else float(accumulation.cells.values[cell]),
            "accum_area_m2": None if accumulation is None else float(accumulation.area_m2.values[cell]),
            "edge_contam": None if accumulation is None else bool(accumulation.area_m2.edge_contaminated[cell]),
            "geometry": Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(cell)]),
        }
        _add_extra(row, cell, extra_cell_fields)
        rows.append(row)
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def build_cell_centres_gdf(
    elevation: Mapping[str, float],
    flow_results: Mapping[str, FlowResult] | None = None,
    dinf_results: Mapping[str, DInfFlowResult] | None = None,
    d6_accumulation: FlowAccumulation | None = None,
    dinf_accumulation: FlowAccumulation | None = None,
    *,
    extra_cell_fields: ExtraFields | None = None,
):
    """Point layer with one feature at every H3 cell centre."""
    gpd, _, Point, _ = _geometry_imports()
    h3 = _h3_import()
    rows = []
    for cell in sorted(elevation):
        d6 = None if flow_results is None else flow_results[cell]
        dinf = None if dinf_results is None else dinf_results[cell]
        lat, lng = h3.cell_to_latlng(cell)
        d6_dir_deg_n_cw = None
        if d6 is not None and d6.flow_to is not None:
            lat2, lng2 = h3.cell_to_latlng(d6.flow_to)
            dlng = ((lng2 - lng + 180.0) % 360.0) - 180.0
            east = math.radians(dlng) * math.cos(math.radians((lat + lat2) / 2.0))
            north = math.radians(lat2 - lat)
            d6_dir_deg_n_cw = math.degrees(math.atan2(east, north)) % 360.0

        dinf_deg_e_ccw = (
            None
            if dinf is None or dinf.direction_rad is None
            else math.degrees(dinf.direction_rad) % 360.0
        )
        dinf_dir_deg_n_cw = (
            None if dinf_deg_e_ccw is None else (90.0 - dinf_deg_e_ccw) % 360.0
        )
        row: dict[str, object] = {
            "h3_id": cell,
            "elevation_m": float(elevation[cell]),
            "d6_flow_to": None if d6 is None else d6.flow_to,
            "d6_drop_m": None if d6 is None else float(d6.drop),
            "d6_distance_m": None if d6 is None else float(d6.distance),
            "d6_slope": None if d6 is None else float(d6.slope),
            "d6_dir_deg_n_cw": d6_dir_deg_n_cw,
            "d6_sink": None if d6 is None else d6.flow_to is None,
            "d6_accum_cells": None if d6_accumulation is None else float(d6_accumulation.cells.values[cell]),
            "d6_accum_area_m2": None if d6_accumulation is None else float(d6_accumulation.area_m2.values[cell]),
            "d6_edge_contam": None if d6_accumulation is None else bool(d6_accumulation.area_m2.edge_contaminated[cell]),
            "dinf_dir_rad": None if dinf is None else dinf.direction_rad,
            "dinf_dir_deg_e_ccw": dinf_deg_e_ccw,
            "dinf_dir_deg_n_cw": dinf_dir_deg_n_cw,
            "dinf_slope": None if dinf is None else float(dinf.slope),
            "dinf_receiver_1": None if dinf is None else dinf.receiver_1,
            "dinf_fraction_1": None if dinf is None else float(dinf.fraction_1),
            "dinf_receiver_2": None if dinf is None else dinf.receiver_2,
            "dinf_fraction_2": None if dinf is None else float(dinf.fraction_2),
            "dinf_sink": None if dinf is None else dinf.sink,
            "dinf_accum_cells": None if dinf_accumulation is None else float(dinf_accumulation.cells.values[cell]),
            "dinf_accum_area_m2": None if dinf_accumulation is None else float(dinf_accumulation.area_m2.values[cell]),
            "dinf_edge_contam": None if dinf_accumulation is None else bool(dinf_accumulation.area_m2.edge_contaminated[cell]),
            "geometry": Point(lng, lat),
        }
        _add_extra(row, cell, extra_cell_fields)
        rows.append(row)
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def build_flow_lines_gdf(flow_results: Mapping[str, FlowResult]):
    gpd, LineString, _, _ = _geometry_imports()
    h3 = _h3_import()
    rows = []
    for cell in sorted(flow_results):
        result = flow_results[cell]
        if result.flow_to is None:
            continue
        lat1, lng1 = h3.cell_to_latlng(cell)
        lat2, lng2 = h3.cell_to_latlng(result.flow_to)
        rows.append(
            {
                "h3_id": cell,
                "flow_to": result.flow_to,
                "drop_m": float(result.drop),
                "distance_m": float(result.distance),
                "slope": float(result.slope),
                "geometry": LineString([(lng1, lat1), (lng2, lat2)]),
            }
        )
    columns = ["h3_id", "flow_to", "drop_m", "distance_m", "slope", "geometry"]
    return gpd.GeoDataFrame(rows, columns=columns, geometry="geometry", crs="EPSG:4326")


def build_sinks_gdf(elevation: Mapping[str, float], flow_results: Mapping[str, FlowResult]):
    gpd, _, Point, _ = _geometry_imports()
    h3 = _h3_import()
    rows = []
    for cell in sorted(flow_results):
        if flow_results[cell].flow_to is not None:
            continue
        lat, lng = h3.cell_to_latlng(cell)
        rows.append({"h3_id": cell, "elevation_m": float(elevation[cell]), "geometry": Point(lng, lat)})
    columns = ["h3_id", "elevation_m", "geometry"]
    return gpd.GeoDataFrame(rows, columns=columns, geometry="geometry", crs="EPSG:4326")


def build_dinf_cells_gdf(
    elevation: Mapping[str, float],
    flow_results: Mapping[str, DInfFlowResult],
    accumulation: FlowAccumulation | None = None,
    *,
    extra_cell_fields: ExtraFields | None = None,
):
    gpd, _, _, Polygon = _geometry_imports()
    h3 = _h3_import()
    rows = []
    for cell in sorted(elevation):
        r = flow_results[cell]
        direction_deg = None if r.direction_rad is None else math.degrees(r.direction_rad)
        row: dict[str, object] = {
            "h3_id": cell,
            "elevation_m": float(elevation[cell]),
            "dir_rad": r.direction_rad,
            "dir_deg_e_ccw": direction_deg,
            "slope": float(r.slope),
            "receiver_1": r.receiver_1,
            "fraction_1": float(r.fraction_1),
            "receiver_2": r.receiver_2,
            "fraction_2": float(r.fraction_2),
            "sink": r.sink,
            "accum_cells": None if accumulation is None else float(accumulation.cells.values[cell]),
            "accum_area_m2": None if accumulation is None else float(accumulation.area_m2.values[cell]),
            "edge_contam": None if accumulation is None else bool(accumulation.area_m2.edge_contaminated[cell]),
            "geometry": Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(cell)]),
        }
        _add_extra(row, cell, extra_cell_fields)
        rows.append(row)
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def _dinf_endpoint(cell: str, result: DInfFlowResult) -> tuple[float, float]:
    h3 = _h3_import()
    lat0, lng0 = h3.cell_to_latlng(cell)
    distances = [
        float(h3.great_circle_distance((lat0, lng0), h3.cell_to_latlng(receiver), unit="m"))
        for receiver, _fraction in result.receivers
    ]
    length_m = sum(distances) / len(distances) if distances else 0.0
    theta = float(result.direction_rad)
    east = math.cos(theta) * length_m
    north = math.sin(theta) * length_m
    lat = lat0 + math.degrees(north / EARTH_RADIUS_M)
    cos_lat = max(1e-12, abs(math.cos(math.radians(lat0))))
    lng = lng0 + math.degrees(east / (EARTH_RADIUS_M * cos_lat))
    return lat, lng


def build_dinf_direction_gdf(flow_results: Mapping[str, DInfFlowResult]):
    gpd, LineString, _, _ = _geometry_imports()
    h3 = _h3_import()
    rows = []
    for cell in sorted(flow_results):
        r = flow_results[cell]
        if r.sink or r.direction_rad is None:
            continue
        lat0, lng0 = h3.cell_to_latlng(cell)
        lat1, lng1 = _dinf_endpoint(cell, r)
        rows.append(
            {
                "h3_id": cell,
                "dir_rad": float(r.direction_rad),
                "dir_deg_e_ccw": math.degrees(r.direction_rad),
                "slope": float(r.slope),
                "receiver_1": r.receiver_1,
                "fraction_1": float(r.fraction_1),
                "receiver_2": r.receiver_2,
                "fraction_2": float(r.fraction_2),
                "geometry": LineString([(lng0, lat0), (lng1, lat1)]),
            }
        )
    columns = [
        "h3_id", "dir_rad", "dir_deg_e_ccw", "slope", "receiver_1", "fraction_1",
        "receiver_2", "fraction_2", "geometry",
    ]
    return gpd.GeoDataFrame(rows, columns=columns, geometry="geometry", crs="EPSG:4326")


def build_dinf_receivers_gdf(flow_results: Mapping[str, DInfFlowResult]):
    gpd, LineString, _, _ = _geometry_imports()
    h3 = _h3_import()
    rows = []
    for cell in sorted(flow_results):
        r = flow_results[cell]
        lat0, lng0 = h3.cell_to_latlng(cell)
        for rank, (receiver, fraction) in enumerate(r.receivers, start=1):
            lat1, lng1 = h3.cell_to_latlng(receiver)
            rows.append(
                {
                    "h3_id": cell,
                    "receiver": receiver,
                    "receiver_rank": rank,
                    "fraction": float(fraction),
                    "slope": float(r.slope),
                    "geometry": LineString([(lng0, lat0), (lng1, lat1)]),
                }
            )
    columns = ["h3_id", "receiver", "receiver_rank", "fraction", "slope", "geometry"]
    return gpd.GeoDataFrame(rows, columns=columns, geometry="geometry", crs="EPSG:4326")


def build_dinf_sinks_gdf(
    elevation: Mapping[str, float], flow_results: Mapping[str, DInfFlowResult]
):
    gpd, _, Point, _ = _geometry_imports()
    h3 = _h3_import()
    rows = []
    for cell in sorted(flow_results):
        if not flow_results[cell].sink:
            continue
        lat, lng = h3.cell_to_latlng(cell)
        rows.append({"h3_id": cell, "elevation_m": float(elevation[cell]), "geometry": Point(lng, lat)})
    columns = ["h3_id", "elevation_m", "geometry"]
    return gpd.GeoDataFrame(rows, columns=columns, geometry="geometry", crs="EPSG:4326")


def export_dem_geopackage(
    elevation: Mapping[str, float],
    output_path: str | Path,
    *,
    extra_cell_fields: ExtraFields | None = None,
) -> Path:
    """Write a preprocessing-only H3 DEM with polygon and cell-centre layers."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    cells = build_cells_gdf(elevation, extra_cell_fields=extra_cell_fields)
    centres = build_cell_centres_gdf(elevation, extra_cell_fields=extra_cell_fields)
    cells.to_file(path, layer="cells", driver="GPKG")
    centres.to_file(path, layer="cell_centres", driver="GPKG")
    return path


def export_flow_geopackage(
    elevation: Mapping[str, float],
    flow_results: Mapping[str, FlowResult] | None,
    output_path: str | Path,
    dinf_results: Mapping[str, DInfFlowResult] | None = None,
    d6_accumulation: FlowAccumulation | None = None,
    dinf_accumulation: FlowAccumulation | None = None,
    *,
    extra_cell_fields: ExtraFields | None = None,
) -> Path:
    """Write D6 and/or D-infinity diagnostic layers to one GeoPackage."""
    if flow_results is None and dinf_results is None:
        raise ValueError("At least one routing result set is required")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    cells = build_cells_gdf(
        elevation,
        flow_results,
        accumulation=d6_accumulation,
        extra_cell_fields=extra_cell_fields,
    )
    cell_centres = build_cell_centres_gdf(
        elevation,
        flow_results,
        dinf_results=dinf_results,
        d6_accumulation=d6_accumulation,
        dinf_accumulation=dinf_accumulation,
        extra_cell_fields=extra_cell_fields,
    )
    cells.to_file(path, layer="cells", driver="GPKG")
    cell_centres.to_file(path, layer="cell_centres", driver="GPKG")

    if flow_results is not None:
        flow_lines = build_flow_lines_gdf(flow_results)
        sinks = build_sinks_gdf(elevation, flow_results)
        if not flow_lines.empty:
            flow_lines.to_file(path, layer="flow_direction", driver="GPKG")
        if not sinks.empty:
            sinks.to_file(path, layer="sinks", driver="GPKG")

    if dinf_results is not None:
        dinf_cells = build_dinf_cells_gdf(
            elevation,
            dinf_results,
            accumulation=dinf_accumulation,
            extra_cell_fields=extra_cell_fields,
        )
        dinf_direction = build_dinf_direction_gdf(dinf_results)
        dinf_receivers = build_dinf_receivers_gdf(dinf_results)
        dinf_sinks = build_dinf_sinks_gdf(elevation, dinf_results)
        dinf_cells.to_file(path, layer="dinf_cells", driver="GPKG")
        if not dinf_direction.empty:
            dinf_direction.to_file(path, layer="dinf_direction", driver="GPKG")
        if not dinf_receivers.empty:
            dinf_receivers.to_file(path, layer="dinf_receivers", driver="GPKG")
        if not dinf_sinks.empty:
            dinf_sinks.to_file(path, layer="dinf_sinks", driver="GPKG")

    return path
