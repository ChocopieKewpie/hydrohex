from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Hashable

import numpy as np

CellId = Hashable


@dataclass(frozen=True)
class NeutralTerrainParameters:
    """Parameters for a reproducible multiscale neutral terrain surface.

    ``roughness`` is a dimensionless 0..1 control. Higher values retain more
    short-wavelength energy and therefore produce a rougher surface.
    ``correlation_length_m`` is the characteristic wavelength around which the
    multiscale spectrum is centered.
    """

    seed: int = 42
    relief_m: float = 500.0
    base_elevation_m: float = 500.0
    roughness: float = 0.65
    correlation_length_m: float = 2_000.0
    octaves: int = 7
    modes_per_octave: int = 8
    regional_slope: float = 0.0
    regional_azimuth_deg_n_cw: float = 90.0

    def validate(self) -> None:
        if self.relief_m <= 0:
            raise ValueError("relief_m must be > 0")
        if not 0.0 <= self.roughness <= 1.0:
            raise ValueError("roughness must be between 0 and 1")
        if self.correlation_length_m <= 0:
            raise ValueError("correlation_length_m must be > 0")
        if self.octaves < 1:
            raise ValueError("octaves must be >= 1")
        if self.modes_per_octave < 1:
            raise ValueError("modes_per_octave must be >= 1")
        if self.regional_slope < 0:
            raise ValueError("regional_slope must be >= 0")


def generate_neutral_surface(
    xy_m: Mapping[CellId, tuple[float, float]],
    params: NeutralTerrainParameters | None = None,
) -> dict[CellId, float]:
    """Generate a continuous, spatially correlated neutral terrain surface.

    The surface is a sum of random plane waves distributed across octave-spaced
    wavelengths.  It is deterministic for a given set of coordinates and seed,
    then normalized so the stochastic component has exactly ``relief_m``
    max-to-min relief.  An optional regional plane is added after normalization.

    The function is topology-agnostic: callers provide local projected-like
    coordinates in metres, so it can be used with H3 or another DGGS.
    """
    params = params or NeutralTerrainParameters()
    params.validate()
    if not xy_m:
        return {}

    cells = sorted(xy_m, key=str)
    coords = np.asarray([xy_m[cell] for cell in cells], dtype=np.float64)
    x = coords[:, 0]
    y = coords[:, 1]

    # Centering reduces phase sensitivity to an arbitrary local coordinate origin.
    x = x - float(x.mean())
    y = y - float(y.mean())

    rng = np.random.default_rng(params.seed)
    field = np.zeros(len(cells), dtype=np.float64)

    # Higher roughness -> slower amplitude decay -> more short-scale structure.
    decay_exponent = 1.55 - params.roughness

    for octave in range(params.octaves):
        wavelength = params.correlation_length_m * (2.0 ** (2 - octave))
        amplitude = 2.0 ** (-decay_exponent * octave)
        octave_field = np.zeros_like(field)

        for _ in range(params.modes_per_octave):
            theta = rng.uniform(0.0, 2.0 * math.pi)
            phase = rng.uniform(0.0, 2.0 * math.pi)
            # Small log-space jitter prevents visibly repeated octave wavelengths.
            jitter = math.exp(rng.uniform(-0.22, 0.22))
            k = 2.0 * math.pi / (wavelength * jitter)
            projection = x * math.cos(theta) + y * math.sin(theta)
            octave_field += np.sin(k * projection + phase)

        octave_field /= math.sqrt(params.modes_per_octave)
        field += amplitude * octave_field

    field -= float(field.mean())
    span = float(field.max() - field.min())
    if span <= np.finfo(np.float64).eps:
        field.fill(0.0)
    else:
        field *= params.relief_m / span
        field -= 0.5 * (float(field.max()) + float(field.min()))

    # Regional azimuth is compass-style: 0=north, 90=east. Positive slope means
    # elevation rises toward that azimuth (and therefore drains the opposite way).
    az = math.radians(params.regional_azimuth_deg_n_cw)
    rise_direction = x * math.sin(az) + y * math.cos(az)
    field += params.regional_slope * rise_direction
    field += params.base_elevation_m

    return {cell: float(z) for cell, z in zip(cells, field, strict=True)}
