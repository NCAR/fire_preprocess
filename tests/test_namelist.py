import os
import tempfile
import unittest

from fire_preprocess.namelist import get_domain_params


class NamelistDomainParamsTest(unittest.TestCase):
    def _write_namelist(self, text):
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".wps", delete=False, dir=os.environ.get("TMPDIR")
        )
        self.addCleanup(lambda: os.path.exists(handle.name) and os.unlink(handle.name))
        with handle:
            handle.write(text)
        return handle.name

    def test_scalar_dx_dy_are_refined_by_parent_grid_ratio(self):
        path = self._write_namelist(
            """
&share
 max_dom = 2,
/
&geogrid
 parent_id         = 1, 1,
 parent_grid_ratio = 1, 3,
 i_parent_start    = 1, 180,
 j_parent_start    = 1, 150,
 e_we              = 802, 1201,
 e_sn              = 802, 1201,
 dx = 300,
 dy = 300,
 map_proj = 'lambert',
 ref_lat = 37.30717,
 ref_lon = -107.4509,
 truelat1 = 30.0,
 truelat2 = 50.0,
 stand_lon = -105.5,
/
"""
        )

        params = get_domain_params(path, domain_index=1)

        self.assertEqual(params["dx"], 100.0)
        self.assertEqual(params["dy"], 100.0)
        self.assertEqual(params["x_mass_offset_from_root"], 179 * 300.0)
        self.assertEqual(params["y_mass_offset_from_root"], 149 * 300.0)

    def test_explicit_dx_dy_arrays_are_preserved(self):
        path = self._write_namelist(
            """
&share
 max_dom = 2,
/
&geogrid
 parent_id         = 1, 1,
 parent_grid_ratio = 1, 3,
 i_parent_start    = 1, 180,
 j_parent_start    = 1, 150,
 e_we              = 802, 1201,
 e_sn              = 802, 1201,
 dx = 300, 90,
 dy = 300, 90,
 map_proj = 'lambert',
 ref_lat = 37.30717,
 ref_lon = -107.4509,
 truelat1 = 30.0,
 truelat2 = 50.0,
 stand_lon = -105.5,
/
"""
        )

        params = get_domain_params(path, domain_index=1)

        self.assertEqual(params["dx"], 90.0)
        self.assertEqual(params["dy"], 90.0)

    def test_recursive_nested_spacing(self):
        path = self._write_namelist(
            """
&share
 max_dom = 3,
/
&geogrid
 parent_id         = 1, 1, 2,
 parent_grid_ratio = 1, 3, 5,
 i_parent_start    = 1, 180, 20,
 j_parent_start    = 1, 150, 30,
 e_we              = 802, 1201, 501,
 e_sn              = 802, 1201, 501,
 dx = 300,
 dy = 300,
 map_proj = 'lambert',
 ref_lat = 37.30717,
 ref_lon = -107.4509,
 truelat1 = 30.0,
 truelat2 = 50.0,
 stand_lon = -105.5,
/
"""
        )

        params = get_domain_params(path, domain_index=2)

        self.assertEqual(params["dx"], 20.0)
        self.assertEqual(params["dy"], 20.0)
        self.assertEqual(params["x_mass_offset_from_root"], 179 * 300.0 + 19 * 100.0)
        self.assertEqual(params["y_mass_offset_from_root"], 149 * 300.0 + 29 * 100.0)


if __name__ == "__main__":
    unittest.main()
