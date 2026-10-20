# Regression tests

The test suite verifies the clipped-source coverage handling and terrain-gradient
behavior added to `fire_preprocess`. The tests use small synthetic arrays and do
not require LANDFIRE, DEM, WPS, or WRF input files.

## Running the tests

From the repository root, run the complete suite with:

```bash
python -m unittest discover -v
```

On Derecho or Casper, the project validation environment can be used directly:

```bash
/glade/work/frediani/casper/anaconda3/envs/py314/bin/python \
    -m unittest discover -v
```

Individual modules can be run with:

```bash
python -m unittest -v tests.test_coverage
python -m unittest -v tests.test_slope
```

The tests should be run from the repository root so Python imports the local
`fire_preprocess` package.

## Current coverage

### `test_coverage.py`

`TerrainInterpolationTest.test_interpolates_plane_and_extends_unused_boundary`
checks interpolation of atmospheric `HGT_M` to the refined fire grid. A planar
terrain field has an exact bilinear solution, which makes subgrid-cell placement
errors apparent. The test also verifies that the extra northern and eastern
fire-grid cells are filled by finite boundary extension.

`CoverageMergeTest.test_uses_only_joint_fuel_and_dem_coverage` checks the clipped
source policy. High-resolution `NFUEL_CAT` and `ZSF` values are retained only
where both source rasters are valid. Elsewhere, fuel is set to the fuel table's
no-fuel category and terrain is taken from the interpolated `HGT_M` background.

### `test_slope.py`

`TerrainGradientTest.test_planar_terrain_has_constant_gradient` checks centered
interior differences, one-sided array-edge differences, row orientation, and the
sign convention for `DZDXF` and `DZDYF`. The geographic test grid has unit
spacing, so the exact gradients are known and map-factor correction is inactive.

`TerrainGradientTest.test_both_gradients_are_zero_outside_valid_stencils` checks
the conservative clipped-coverage rule. Both gradient components are zero where
either finite-difference stencil crosses the high-resolution coverage boundary,
while the expected planar gradients are retained on complete stencils.
