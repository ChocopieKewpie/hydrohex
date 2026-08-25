from hydrohex.core import compute_flow_directions
from hydrohex.datasets import make_plane
from hydrohex.h3_grid import cell, distance_m, neighbors

center = cell(-36.8485, 174.7633, 12)
cells = sorted({center, *neighbors(center), *[n for c in neighbors(center) for n in neighbors(c)]})
dem = make_plane(cells, center)
flow = compute_flow_directions(dem, neighbors, distance_m)

print("cell, elevation_m, flow_to, slope")
for h in cells:
    r = flow[h]
    print(f"{h}, {dem[h]:.3f}, {r.flow_to}, {r.slope:.8f}")
