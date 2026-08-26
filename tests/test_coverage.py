"""Test atmospheric-terrain interpolation and clipped raster coverage."""

from __future__ import annotations

import unittest

import numpy as np

from fire_preprocess.coverage import (
    interpolate_hgt_to_fire_grid,
    merge_fire_coverage,
)
from fire_preprocess.fuel_tables import get_fuel_table


#--------------------------------------------------------------------------------
# Terrain interpolation
#--------------------------------------------------------------------------------

class TerrainInterpolationTest(unittest.TestCase):
    """Verify subgrid geometry and finite boundary filling."""

    def test_interpolates_plane_and_extends_unused_boundary(self) -> None:
        """A linear HGT_M field remains linear over active fire cells."""
        y_index, x_index = np.indices((3, 4), dtype=np.float32)
        terrain = 10.0 * y_index + 2.0 * x_index

        background = interpolate_hgt_to_fire_grid(
            terrain,
            sr_x=2,
            sr_y=2,
            output_shape=(8, 10),
        )

        y_coordinates = (np.arange(6) - 0.5) / 2.0
        x_coordinates = (np.arange(8) - 0.5) / 2.0
        expected_active = (
            10.0 * y_coordinates[:, None] + 2.0 * x_coordinates[None, :]
        )
        np.testing.assert_allclose(background[:6, :8], expected_active)
        expected_east = np.repeat(expected_active[:, -1, None], 2, axis=1)
        np.testing.assert_allclose(background[:6, 8:], expected_east)
        expected_north = np.repeat(background[5:6, :], 2, axis=0)
        np.testing.assert_allclose(background[6:, :], expected_north)
        self.assertTrue(np.isfinite(background).all())


#--------------------------------------------------------------------------------
# Clipped high-resolution coverage
#--------------------------------------------------------------------------------

class CoverageMergeTest(unittest.TestCase):
    """Verify no-fuel and atmospheric-terrain behavior outside coverage."""

    def test_uses_only_joint_fuel_and_dem_coverage(self) -> None:
        """Only coincident valid pixels receive high-resolution fire data."""
        fuel_table = get_fuel_table("fbfm13")
        nfuel_raw = np.array([[1.0, 2.0], [3.0, np.nan]], dtype=np.float32)
        zsf_raw = np.array([[101.0, 102.0], [103.0, np.nan]], dtype=np.float32)
        fuel_valid = np.array([[True, True], [True, False]])
        dem_valid = np.array([[True, False], [True, False]])
        background = np.array([[10.0, 20.0], [30.0, 40.0]], dtype=np.float32)

        nfuel, zsf, joint_valid = merge_fire_coverage(
            nfuel_raw,
            zsf_raw,
            fuel_valid,
            dem_valid,
            background,
            fuel_table,
        )

        np.testing.assert_array_equal(
            joint_valid, np.array([[True, False], [True, False]])
        )
        np.testing.assert_array_equal(
            nfuel, np.array([[1.0, 14.0], [3.0, 14.0]], dtype=np.float32)
        )
        np.testing.assert_array_equal(
            zsf, np.array([[101.0, 20.0], [103.0, 40.0]], dtype=np.float32)
        )


if __name__ == "__main__":
    unittest.main()
