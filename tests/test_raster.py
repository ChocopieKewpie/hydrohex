from pathlib import Path

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
from rasterio.transform import from_origin

from hydrohex.raster import raster_bounds_lonlat, sample_raster_lonlat


def _write_test_raster(path: Path) -> Path:
    data = np.arange(16, dtype="float32").reshape(4, 4)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(0.0, 4.0, 1.0, 1.0),
        nodata=-9999.0,
    ) as dst:
        dst.write(data, 1)
    return path


def test_nearest_sampling_at_pixel_centres(tmp_path):
    path = _write_test_raster(tmp_path / "dem.tif")
    values = sample_raster_lonlat(
        path,
        [(0.5, 3.5), (2.5, 1.5)],
        sampling="nearest",
    )
    assert values == pytest.approx([0.0, 10.0])


def test_bilinear_sampling_between_four_pixels(tmp_path):
    path = _write_test_raster(tmp_path / "dem.tif")
    values = sample_raster_lonlat(path, [(1.0, 3.0)], sampling="bilinear")
    assert values == pytest.approx([2.5])


def test_raster_bounds_are_reported_in_lonlat(tmp_path):
    path = _write_test_raster(tmp_path / "dem.tif")
    assert raster_bounds_lonlat(path) == pytest.approx((0.0, 0.0, 4.0, 4.0))


def test_sampling_method_validation(tmp_path):
    path = _write_test_raster(tmp_path / "dem.tif")
    with pytest.raises(ValueError):
        sample_raster_lonlat(path, [(1.0, 1.0)], sampling="cubic")


def test_raster_open_retries_windows_share_violation(monkeypatch):
    import hydrohex.raster as raster

    class FakeDataset:
        def __init__(self):
            self.closed = False
        def close(self):
            self.closed = True

    dataset = FakeDataset()
    calls = {"count": 0}

    class FakeRasterio:
        @staticmethod
        def open(_path):
            calls["count"] += 1
            if calls["count"] == 1:
                exc = PermissionError(13, "file is being used by another process")
                exc.winerror = 32
                raise exc
            return dataset

    monkeypatch.setattr(raster.time, "sleep", lambda _: None)
    with raster._open_raster_with_retry(FakeRasterio, "dem.tif", retries=2) as src:
        assert src is dataset

    assert calls["count"] == 2
    assert dataset.closed
