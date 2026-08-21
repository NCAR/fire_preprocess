"""Compute fire-grid terrain gradients (DZDXF, DZDYF) from ZSF.

For real cases these two fields are read from the input file and never
recomputed: WRF-CFBM passes grid%dzdxf/dzdyf into Init_fire_state_within_wrf
(dyn_em/start_em.F), and state_mod.F90 assigns them straight into the fire
state.  Only the idealized initializer (dyn_em/module_initialize_fire.F)
derives them from ZSF.  So whenever ZSF is replaced, DZDXF/DZDYF have to be
replaced with it, or slope makes no contribution to the rate of spread.

The stencil matches geogrid's calc_dfdx/calc_dfdy in
WPS geogrid/src/process_tile_module.f90: a centred difference over two fire
cells in the interior, one-sided at the domain edges.

The map scale factor is applied, so the gradients stay correct on domains
large enough for it to depart appreciably from 1.  Note that the sense of the
correction here is the opposite of geogrid's: WRF measures grid spacing in
projection space and takes the true distance between grid points to be
dx/MAPFAC (dyn_em/module_diffusion_em.F builds its physical mixing length as
sqrt(dx/msftx * dy/msfty)), so a physical gradient must *multiply* by the map
factor.  geogrid's calc_dfdx divides by it instead.
"""
import numpy as np
from pyproj import CRS, Proj, Transformer

from .wrf_domain import WRF_SPHERE_RADIUS


def map_scale_factors(fire_grid):
    """Return (mapfac_x, mapfac_y) at fire-grid cell centres.

    Both arrays are float64, shaped (ny_fire, nx_fire), in WRF row order with
    row 0 southernmost so they align with ZSF.  For the conformal projections
    WRF supports these two are equal to within roundoff; they are returned
    separately anyway, mirroring geogrid's use of MAPFAC_MX and MAPFAC_MY.

    A geographic (lat-lon) fire grid gets 1.0, since its spacing is in degrees
    rather than projected metres and the metric terms do not apply.
    """
    ny, nx = fire_grid.ny_fire, fire_grid.nx_fire
    ones = np.ones((ny, nx))
    if fire_grid.crs.is_geographic:
        return ones, ones

    # from_origin() yields an axis-aligned transform, so cell centres separate
    # into an independent 1-D x and 1-D y sequence.
    t = fire_grid.transform
    xs = t.c + (np.arange(nx) + 0.5) * t.a
    ys = t.f + (np.arange(ny) + 0.5) * t.e
    xg, yg = np.meshgrid(xs, ys)

    geo_crs = CRS.from_proj4(
        f"+proj=longlat +a={WRF_SPHERE_RADIUS} +b={WRF_SPHERE_RADIUS} +no_defs"
    )
    lon, lat = Transformer.from_crs(
        fire_grid.crs, geo_crs, always_xy=True
    ).transform(xg, yg)

    factors = Proj(fire_grid.crs).get_factors(lon, lat, radians=False)
    mfx = np.asarray(factors.parallel_scale, dtype=np.float64)
    mfy = np.asarray(factors.meridional_scale, dtype=np.float64)

    # Row 0 of the transform is the northernmost row; ZSF is south-first.
    return np.flipud(mfx), np.flipud(mfy)


def compute_slope(zsf: np.ndarray, fire_grid):
    """Return (dzdxf, dzdyf) as float32 arrays shaped like *zsf*.

    Args:
        zsf:       terrain height on the fire grid, shape (ny_fire, nx_fire),
                   row 0 = southernmost (WRF/WPS netCDF order)
        fire_grid: the FireGrid the terrain was reprojected onto; supplies the
                   cell spacing and the projection the map factor comes from

    Because row 0 is the southernmost row, axis 0 increases northward and
    axis 1 increases eastward, so both gradients are positive uphill toward
    increasing x/y — the same sign convention WRF-Fire expects.
    """
    z = np.asarray(zsf, dtype=np.float64)
    if z.shape[0] < 2 or z.shape[1] < 2:
        raise ValueError(f"ZSF must be at least 2x2 to differentiate; got {z.shape}")
    if z.shape != (fire_grid.ny_fire, fire_grid.nx_fire):
        raise ValueError(
            f"ZSF shape {z.shape} does not match the fire grid "
            f"({fire_grid.ny_fire}, {fire_grid.nx_fire})"
        )

    dx_fire, dy_fire = fire_grid.dx, fire_grid.dy
    dzdxf = np.empty_like(z)
    dzdyf = np.empty_like(z)

    dzdxf[:, 1:-1] = (z[:, 2:] - z[:, :-2]) / (2.0 * dx_fire)
    dzdxf[:, 0] = (z[:, 1] - z[:, 0]) / dx_fire
    dzdxf[:, -1] = (z[:, -1] - z[:, -2]) / dx_fire

    dzdyf[1:-1, :] = (z[2:, :] - z[:-2, :]) / (2.0 * dy_fire)
    dzdyf[0, :] = (z[1, :] - z[0, :]) / dy_fire
    dzdyf[-1, :] = (z[-1, :] - z[-2, :]) / dy_fire

    mapfac_x, mapfac_y = map_scale_factors(fire_grid)
    dzdxf *= mapfac_x
    dzdyf *= mapfac_y

    return dzdxf.astype(np.float32), dzdyf.astype(np.float32)
