"""Test fire-grid terrain gradients and high-resolution coverage masking."""

from __future__ import annotations

import unittest

import numpy as np
from pyproj import CRS
from rasterio.transform import from_origin

from fire_preprocess.fire_grid import FireGrid
from fire_preprocess.slope import compute_slope, gradient_coverage_mask


#--------------------------------------------------------------------------------
# Test grid
#--------------------------------------------------------------------------------

def make_geographic_grid(nx: int = 7, ny: int = 6) -> FireGrid:
    """Return a unit-spacing grid for exact finite-difference tests."""
    return FireGrid(
        nx_fire=nx,
        ny_fire=ny,
        dx=1.0,
        dy=1.0,
        transform=from_origin(0.0, float(ny), 1.0, 1.0),
        crs=CRS.from_epsg(4326),
    )


#--------------------------------------------------------------------------------
# Gradient calculations
#--------------------------------------------------------------------------------

class TerrainGradientTest(unittest.TestCase):
    """Verify planar derivatives and conservative coverage masking."""

    def test_planar_terrain_has_constant_gradient(self) -> None:
        """Centered and one-sided differences recover a linear surface."""
        fire_grid = make_geographic_grid()
        y_index, x_index = np.indices(
            (fire_grid.ny_fire, fire_grid.nx_fire), dtype=np.float32
        )
        zsf = 1000.0 + 2.0 * x_index + 3.0 * y_index

        dzdxf, dzdyf = compute_slope(zsf, fire_grid)

        np.testing.assert_allclose(dzdxf, 2.0)
        np.testing.assert_allclose(dzdyf, 3.0)

    def test_both_gradients_are_zero_outside_valid_stencils(self) -> None:
        """A clipped fire area does not form gradients across its boundary."""
        fire_grid = make_geographic_grid()
        y_index, x_index = np.indices(
            (fire_grid.ny_fire, fire_grid.nx_fire), dtype=np.float32
        )
        zsf = 1000.0 + 2.0 * x_index + 3.0 * y_index
        valid = np.zeros(zsf.shape, dtype=bool)
        valid[1:5, 1:6] = True

        dzdxf, dzdyf = compute_slope(zsf, fire_grid, valid)
        stencil = gradient_coverage_mask(valid)

        np.testing.assert_allclose(dzdxf[stencil], 2.0)
        np.testing.assert_allclose(dzdyf[stencil], 3.0)
        np.testing.assert_array_equal(dzdxf[~stencil], 0.0)
        np.testing.assert_array_equal(dzdyf[~stencil], 0.0)


if __name__ == "__main__":
    unittest.main()
