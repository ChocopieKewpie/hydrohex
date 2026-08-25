import pytest

h3 = pytest.importorskip("h3")

from hydrohex.core import flow_direction
from hydrohex.datasets import make_bowl, make_plane
from hydrohex.h3_grid import distance_m, neighbors


def test_normal_h3_cell_has_six_neighbors():
    c = h3.latlng_to_cell(-36.8485, 174.7633, 12)
    assert len(neighbors(c)) == 6


def test_plane_routes_center_downhill():
    c = h3.latlng_to_cell(-36.8485, 174.7633, 12)
    cells = sorted(h3.grid_disk(c, 2))
    dem = make_plane(cells, c)
    r = flow_direction(c, dem, neighbors, distance_m)
    assert r.flow_to in neighbors(c)
    assert r.drop > 0
    assert r.slope > 0


def test_bowl_center_is_sink():
    c = h3.latlng_to_cell(-36.8485, 174.7633, 12)
    cells = sorted(h3.grid_disk(c, 2))
    dem = make_bowl(cells, c)
    r = flow_direction(c, dem, neighbors, distance_m)
    assert r.flow_to is None


def test_dinf_plane_routes_to_one_or_two_h3_neighbors():
    from hydrohex.dinf import dinf_flow_direction
    from hydrohex.h3_grid import local_xy_m

    c = h3.latlng_to_cell(-36.8485, 174.7633, 12)
    cells = sorted(h3.grid_disk(c, 2))
    dem = make_plane(cells, c)
    r = dinf_flow_direction(c, dem, neighbors, local_xy_m)
    assert not r.sink
    assert 1 <= len(r.receivers) <= 2
    assert all(receiver in neighbors(c) for receiver, _ in r.receivers)
    assert sum(fraction for _, fraction in r.receivers) == pytest.approx(1.0)
    assert r.slope > 0.0


def test_dinf_bowl_center_is_sink():
    from hydrohex.dinf import dinf_flow_direction
    from hydrohex.h3_grid import local_xy_m

    c = h3.latlng_to_cell(-36.8485, 174.7633, 12)
    cells = sorted(h3.grid_disk(c, 2))
    dem = make_bowl(cells, c)
    r = dinf_flow_direction(c, dem, neighbors, local_xy_m)
    assert r.sink


def test_equivalent_radius_preserves_res8_radius4_footprint_at_res12():
    from hydrohex.datasets import equivalent_disk_radius

    assert equivalent_disk_radius(12, reference_resolution=8, reference_radius=4) == 220

