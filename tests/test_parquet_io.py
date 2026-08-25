from __future__ import annotations

from pathlib import Path

import pytest

from hydrohex.io import (
    _choose_elevation_field,
    _choose_h3_field,
    _normalise_h3_cell,
    read_dem,
)


def test_raster2dggs_h3_field_autodetection_uses_finest_resolution():
    fields = ["band_1", "geometry", "h3_13", "h3_07"]
    assert _choose_h3_field(fields) == "h3_13"


def test_raster2dggs_band_1_is_preferred_elevation_field():
    fields = ["band_1", "band_2", "geometry", "h3_13", "h3_07"]
    assert _choose_elevation_field(fields, {"band_1", "band_2"}) == "band_1"


def test_ambiguous_numeric_parquet_values_require_override():
    with pytest.raises(ValueError, match="ambiguous"):
        _choose_elevation_field(
            ["temperature", "height", "h3_13"],
            {"temperature", "height"},
        )


def test_uint64_h3_ids_are_normalised_to_hex_strings():
    value = int("8d28308280f18ff", 16)
    assert _normalise_h3_cell(value) == "8d28308280f18ff"


def test_read_partitioned_raster2dggs_style_parquet_dataset(tmp_path: Path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")

    root = tmp_path / "taranaki_h3"
    partition = root / "h3_07=872830828ffffff"
    partition.mkdir(parents=True)
    table = pa.table(
        {
            "h3_13": ["8d28308280f18ff", "8d28308280f19ff"],
            "band_1": [2518.25, 2509.75],
            "geometry": [b"ignored", b"ignored"],
        }
    )
    pq.write_table(table, partition / "part.0.parquet")

    result = read_dem(root)
    assert result == {
        "8d28308280f18ff": pytest.approx(2518.25),
        "8d28308280f19ff": pytest.approx(2509.75),
    }


def test_read_single_parquet_with_explicit_fields(tmp_path: Path):
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")

    path = tmp_path / "dem.pq"
    pq.write_table(
        pa.table({"cell": ["abc", "def"], "height": [10.0, 9.0]}),
        path,
    )
    assert read_dem(path, id_field="cell", elevation_field="height") == {
        "abc": 10.0,
        "def": 9.0,
    }
