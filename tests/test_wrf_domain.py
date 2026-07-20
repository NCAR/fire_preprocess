import os
import tempfile
import unittest

import netCDF4 as nc

from fire_preprocess.wrf_domain import read_domain_from_file


class WRFDomainFileTest(unittest.TestCase):
    def _make_file(self, lat_name, lon_name):
        handle = tempfile.NamedTemporaryFile(
            suffix=".nc", delete=False, dir=os.environ.get("TMPDIR")
        )
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))

        with nc.Dataset(handle.name, "w") as ds:
            ds.createDimension("Time", 1)
            ds.createDimension("south_north", 3)
            ds.createDimension("west_east", 4)
            lat = ds.createVariable(lat_name, "f4", ("Time", "south_north", "west_east"))
            lon = ds.createVariable(lon_name, "f4", ("Time", "south_north", "west_east"))
            lat[:] = 37.0
            lon[:] = -107.0
            ds.MAP_PROJ = 6
            ds.TRUELAT1 = 0.0
            ds.TRUELAT2 = 0.0
            ds.STAND_LON = 0.0
            ds.DX = 100.0
            ds.DY = 100.0
        return handle.name

    def _make_file_without_coordinates(self):
        handle = tempfile.NamedTemporaryFile(
            suffix=".nc", delete=False, dir=os.environ.get("TMPDIR")
        )
        handle.close()
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))

        with nc.Dataset(handle.name, "w") as ds:
            ds.MAP_PROJ = 6
            ds.TRUELAT1 = 0.0
            ds.TRUELAT2 = 0.0
            ds.STAND_LON = 0.0
            ds.DX = 100.0
            ds.DY = 100.0
        return handle.name

    def test_reads_wrfinput_mass_coordinates(self):
        path = self._make_file("XLAT", "XLONG")

        domain = read_domain_from_file(path, sr_x=4, sr_y=4)

        self.assertEqual(domain.nx, 4)
        self.assertEqual(domain.ny, 3)
        self.assertEqual(domain.dx, 100.0)
        self.assertEqual(domain.dy, 100.0)
        self.assertEqual(domain.sr_x, 4)
        self.assertEqual(domain.sr_y, 4)

    def test_preserves_wps_mass_coordinates(self):
        path = self._make_file("XLAT_M", "XLONG_M")

        domain = read_domain_from_file(path, sr_x=2, sr_y=2)

        self.assertEqual(domain.nx, 4)
        self.assertEqual(domain.ny, 3)
        self.assertEqual(domain.sr_x, 2)
        self.assertEqual(domain.sr_y, 2)

    def test_uses_namelist_fallback_without_mass_coordinates(self):
        path = self._make_file_without_coordinates()
        namelist_params = {
            "ref_lon": -107.0,
            "ref_lat": 37.0,
            "ref_x": 3.0,
            "ref_y": 4.0,
            "root_dx": 100.0,
            "root_dy": 100.0,
            "x_mass_offset_from_root": 200.0,
            "y_mass_offset_from_root": 300.0,
            "e_we": 5,
            "e_sn": 6,
        }

        domain = read_domain_from_file(
            path, sr_x=4, sr_y=4, namelist_params=namelist_params
        )

        self.assertEqual(domain.nx, 4)
        self.assertEqual(domain.ny, 5)
        self.assertEqual(domain.sr_x, 4)
        self.assertEqual(domain.sr_y, 4)


if __name__ == "__main__":
    unittest.main()
