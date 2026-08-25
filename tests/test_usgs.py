import pytest

from hydrohex.usgs import (
    DEFAULT_BOULDER_BBOX,
    DEFAULT_LOCH_VALE_BBOX,
    MAX_IMAGE_SIZE,
    USGS_3DEP_IMAGE_SERVER,
    build_usgs_3dep_export_url,
    site_bbox,
)


def test_usgs_url_builds_1m_loch_vale_export():
    url, meta = build_usgs_3dep_export_url(DEFAULT_LOCH_VALE_BBOX, pixel_size_m=1.0)
    assert url.startswith(USGS_3DEP_IMAGE_SERVER)
    assert "format=tiff" in url
    assert "pixelType=F32" in url
    assert 3_000 < meta.width < MAX_IMAGE_SIZE
    assert 3_000 < meta.height < MAX_IMAGE_SIZE
    assert meta.requested_pixel_size_m == 1.0


def test_site_registry_defaults_to_loch_vale_and_keeps_boulder():
    assert site_bbox() == DEFAULT_LOCH_VALE_BBOX
    assert site_bbox("boulder") == DEFAULT_BOULDER_BBOX
    with pytest.raises(ValueError):
        site_bbox("not-a-site")


def test_usgs_bbox_validation():
    with pytest.raises(ValueError):
        build_usgs_3dep_export_url((-105.0, 40.0, -106.0, 39.0))


def test_usgs_service_size_limit_is_enforced():
    with pytest.raises(ValueError):
        build_usgs_3dep_export_url((-110.0, 35.0, -100.0, 45.0), pixel_size_m=1.0)


def test_fetch_streams_directly_to_final_path_without_temp_rename(tmp_path, monkeypatch):
    import io
    import hydrohex.usgs as usgs

    class Response(io.BytesIO):
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            self.close()
            return False

    output = tmp_path / "loch_vale.tif"
    payload = b"II*\x00" + b"dem-data"
    monkeypatch.setattr(usgs, "urlopen", lambda *args, **kwargs: Response(payload))

    # The new downloader must not rename a temporary file into place.
    monkeypatch.setattr(
        type(output),
        "replace",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("rename used")),
    )

    meta = usgs.fetch_usgs_3dep(
        output,
        bbox=(-105.688, 40.266, -105.687, 40.267),
        pixel_size_m=10.0,
    )

    assert output.read_bytes() == payload
    assert output.with_suffix(".tif.json").exists()
    assert meta.requested_pixel_size_m == 10.0
    assert not list(tmp_path.glob("tmp*.tif"))


def test_failed_direct_fetch_does_not_leave_completion_sidecar(tmp_path, monkeypatch):
    import hydrohex.usgs as usgs

    output = tmp_path / "loch_vale.tif"

    class BrokenResponse:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def read(self, _size=-1):
            raise ConnectionError("network interrupted")

    monkeypatch.setattr(usgs, "urlopen", lambda *args, **kwargs: BrokenResponse())

    with pytest.raises(ConnectionError):
        usgs.fetch_usgs_3dep(output, bbox=(-105.688, 40.266, -105.687, 40.267), pixel_size_m=10.0)

    assert not output.with_suffix(".tif.json").exists()


def test_loch_vale_1m_fetch_uses_tiled_mosaic(tmp_path, monkeypatch):
    import hydrohex.usgs as usgs

    output = tmp_path / "loch_vale.tif"
    called = {}

    def fake_tiled(path, *, metadata, timeout_s, tile_size):
        import numpy as np
        import rasterio
        from rasterio.transform import from_bounds

        called["width"] = metadata.width
        called["height"] = metadata.height
        called["tile_size"] = tile_size
        west, south, east, north = metadata.bbox_lonlat
        profile = {
            "driver": "GTiff",
            "width": metadata.width,
            "height": metadata.height,
            "count": 1,
            "dtype": "float32",
            "crs": "EPSG:4326",
            "transform": from_bounds(west, south, east, north, metadata.width, metadata.height),
            "nodata": -9999.0,
        }
        with rasterio.open(path, "w", **profile) as dst:
            # Write by blocks/rows to avoid allocating the full test raster twice.
            row = np.zeros((1, metadata.width), dtype="float32")
            for y in range(metadata.height):
                dst.write(row, 1, window=((y, y + 1), (0, metadata.width)))
        return 16

    monkeypatch.setattr(usgs, "_fetch_tiled_mosaic", fake_tiled)
    monkeypatch.setattr(
        usgs,
        "_fetch_direct_to_path",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("large request fetched directly")),
    )

    meta = usgs.fetch_usgs_3dep(output, bbox=usgs.DEFAULT_LOCH_VALE_BBOX, pixel_size_m=1.0)

    assert meta.delivery_mode == "tiled"
    assert meta.tile_count == 16
    assert called["width"] > 3000
    assert called["height"] > 3000
    assert called["tile_size"] == usgs.DEFAULT_TILE_SIZE
    assert output.exists()
    assert output.with_suffix(".tif.json").exists()


def test_tile_windows_cover_grid_without_overlap():
    import hydrohex.usgs as usgs

    windows = list(usgs._tile_windows(2500, 2100, 1024))
    assert len(windows) == 9
    area = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in windows)
    assert area == 2500 * 2100
    assert windows[0] == (0, 0, 1024, 1024)
    assert windows[-1] == (2048, 2048, 2500, 2100)


def test_export_url_disables_arcgis_square_pixel_extent_adjustment():
    import hydrohex.usgs as usgs
    from urllib.parse import parse_qs, urlparse

    url, _ = usgs.build_usgs_3dep_export_url(
        usgs.DEFAULT_LOCH_VALE_BBOX,
        pixel_size_m=1.0,
    )
    params = parse_qs(urlparse(url).query)
    assert params["returnSquarePixels"] == ["false"]


def test_tiled_mosaic_reprojects_adjusted_tile_extents_to_one_global_grid(tmp_path, monkeypatch):
    """Regression for visible 1024-row bands in ArcGIS tiled downloads.

    ArcGIS may return a GeoTIFF whose transform is slightly different from the
    requested bbox. The mosaic must use each returned tile's georeferencing,
    not paste its array blindly into the requested pixel window.
    """
    import numpy as np
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.transform import from_bounds, xy
    from urllib.parse import parse_qs, urlparse
    import hydrohex.usgs as usgs

    def fake_fetch(url, *, timeout_s):
        params = parse_qs(urlparse(url).query)
        west, south, east, north = map(float, params["bbox"][0].split(","))
        width, height = map(int, params["size"][0].split(","))

        # Simulate exportImage expanding every requested tile independently.
        dx = east - west
        dy = north - south
        src_bounds = (
            west - 0.08 * dx,
            south - 0.08 * dy,
            east + 0.08 * dx,
            north + 0.08 * dy,
        )
        transform = from_bounds(*src_bounds, width, height)
        rows, cols = np.indices((height, width))
        xs = transform.c + (cols + 0.5) * transform.a
        ys = transform.f + (rows + 0.5) * transform.e
        data = (1000.0 * xs + 500.0 * ys).astype("float32")

        with MemoryFile() as mem:
            with mem.open(
                driver="GTiff",
                width=width,
                height=height,
                count=1,
                dtype="float32",
                crs="EPSG:4326",
                transform=transform,
                nodata=-9999.0,
            ) as dst:
                dst.write(data, 1)
            return mem.read()

    monkeypatch.setattr(usgs, "_fetch_tiff_bytes", fake_fetch)
    output = tmp_path / "aligned.tif"
    bbox = (-105.0, 40.0, -104.988, 40.010)
    metadata = usgs.USGSFetchMetadata(
        source="test",
        bbox_lonlat=bbox,
        requested_pixel_size_m=1.0,
        width=12,
        height=10,
        url="test",
    )

    count = usgs._fetch_tiled_mosaic(
        output,
        metadata=metadata,
        timeout_s=1,
        tile_size=5,
    )
    assert count == 6

    with rasterio.open(output) as src:
        actual = src.read(1)
        rows, cols = np.indices(actual.shape)
        xs = src.transform.c + (cols + 0.5) * src.transform.a
        ys = src.transform.f + (rows + 0.5) * src.transform.e
        expected = 1000.0 * xs + 500.0 * ys

    # A linear field should remain continuous across every tile seam after the
    # returned tile transforms are respected and reprojected to the global grid.
    assert np.max(np.abs(actual - expected)) < 0.05
    assert np.max(np.abs(actual[4, :] - actual[5, :])) < 1.0
