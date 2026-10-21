#!/usr/bin/env python3
# Copyright 2026      Research Applications Laboratory (RAL),
#                     National Center for Atmospheric Research (NCAR),
#                     University Corporation for Atmospheric Research (UCAR)
#
#--------------------------------------------------------------------------------
# Created by Maria Frediani (frediani@ucar.edu) on 2026-10-21
#--------------------------------------------------------------------------------
# run /glade/work/frediani/casper/anaconda3/envs/py314/bin/python -m unittest -v tests.test_fire_grid
"""Check fire-grid dimensions against small, in-memory WPS datasets."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import netCDF4 as nc

from fire_preprocess.fire_grid import build_fire_grid
from fire_preprocess.wrf_domain import WRFDomain, read_domain_from_file


#--------------------------------------------------------------------------------
# WPS geometry fixture
#--------------------------------------------------------------------------------

def read_fixture(
    sr_x: int,
    sr_y: int,
    nx_fire: int | None = None,
    ny_fire: int | None = None,
) -> WRFDomain:
    """Read a non-square atmospheric domain without creating a disk file."""
    dataset = nc.Dataset("geogrid", "w", diskless=True, persist=False)
    for name, size in (("Time", 1), ("south_north", 5), ("west_east", 7)):
        dataset.createDimension(name, size)
    for name, size in (("west_east_subgrid", nx_fire),
                       ("south_north_subgrid", ny_fire)):
        if size is not None:
            dataset.createDimension(name, size)
    dataset.setncatts({
        "MAP_PROJ": 1, "TRUELAT1": 30.0, "TRUELAT2": 60.0,
        "STAND_LON": -105.0, "DX": 100.0, "DY": 200.0,
        "sr_x": sr_x, "sr_y": sr_y,
    })
    for name, value in (("XLAT_M", 40.0), ("XLONG_M", -105.0)):
        variable = dataset.createVariable(
            name, "f4", ("Time", "south_north", "west_east")
        )
        variable[:] = value
    with patch("fire_preprocess.wrf_domain.nc.Dataset", return_value=dataset):
        return read_domain_from_file("in-memory-geogrid.nc", sr_x, sr_y)


#--------------------------------------------------------------------------------
# Existing and newly constructed fire grids
#--------------------------------------------------------------------------------

class FireGridDimensionsTest(unittest.TestCase):
    """Keep the output shape and cell locations consistent with WPS inputs."""

    def test_unrefined_grid_uses_existing_mass_grid_dimensions(self) -> None:
        """A ratio-one geogrid must not acquire an extra row or column."""
        domain = read_fixture(1, 1, nx_fire=7, ny_fire=5)
        grid = build_fire_grid(domain)
        self.assertEqual((grid.ny_fire, grid.nx_fire), (5, 7))
        self.assertEqual((grid.dx, grid.dy), (100.0, 200.0))
        self.assertAlmostEqual(grid.transform.c, domain.x_fire_sw)
        self.assertAlmostEqual(grid.transform.f, domain.y_fire_sw + 1000.0)
        # Raster rows run north to south; this is the southwest cell center.
        x_sw, y_sw = grid.transform * (0.5, grid.ny_fire - 0.5)
        self.assertAlmostEqual(x_sw, domain.x_fire_sw + 50.0)
        self.assertAlmostEqual(y_sw, domain.y_fire_sw + 100.0)

    def test_refined_grids_keep_their_existing_extent(self) -> None:
        """Ratios two and four retain WPS padding, including unequal ratios."""
        for sr_x, sr_y, nx_fire, ny_fire in ((2, 2, 16, 12),
                                          (4, 4, 32, 24),
                                          (2, 3, 16, 18)):
            with self.subTest(sr_x=sr_x, sr_y=sr_y):
                domain = read_fixture(sr_x, sr_y, nx_fire, ny_fire)
                grid = build_fire_grid(domain)
                self.assertEqual((grid.ny_fire, grid.nx_fire), (ny_fire, nx_fire))
                self.assertAlmostEqual(grid.nx_fire * grid.dx, 800.0)
                self.assertAlmostEqual(grid.ny_fire * grid.dy, 1200.0)
                self.assertAlmostEqual(grid.transform.c, domain.x_fire_sw)
                self.assertAlmostEqual(grid.transform.f,
                                       domain.y_fire_sw + 1200.0)

    def test_missing_dimensions_keep_the_construction_default(self) -> None:
        """Files without a fire grid retain the existing padded-grid rule."""
        for ratio, expected in ((1, (6, 8)), (2, (12, 16))):
            with self.subTest(ratio=ratio):
                grid = build_fire_grid(read_fixture(ratio, ratio))
                self.assertEqual((grid.ny_fire, grid.nx_fire), expected)

    def test_dimensions_are_resolved_independently(self) -> None:
        """An existing west-east extent is retained when south-north is absent."""
        grid = build_fire_grid(read_fixture(1, 2, nx_fire=7))
        self.assertEqual((grid.ny_fire, grid.nx_fire), (12, 7))

    def test_incompatible_existing_dimensions_are_rejected(self) -> None:
        """A different requested refinement must not silently rescale a grid."""
        for nx_fire, ny_fire, dimension in ((16, 24, "west_east_subgrid"),
                                          (32, 12, "south_north_subgrid")):
            with self.subTest(dimension=dimension):
                domain = read_fixture(4, 4, nx_fire, ny_fire)
                with self.assertRaisesRegex(ValueError, dimension):
                    build_fire_grid(domain)


if __name__ == "__main__":
    unittest.main()
