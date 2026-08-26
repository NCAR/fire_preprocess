"""Compute fire-grid terrain gradients (DZDXF, DZDYF) from merged ZSF.

For real cases these two fields are read from the input file and never
recomputed: WRF-CFBM passes grid%dzdxf/dzdyf into Init_fire_state_within_wrf
(dyn_em/start_em.F), and state_mod.F90 assigns them straight into the fire
state.  Only the idealized initializer (dyn_em/module_initialize_fire.F)
derives them from ZSF.  So whenever ZSF is replaced, DZDXF/DZDYF have to be
replaced with it, or slope makes no contribution to the rate of spread.

The stencil matches geogrid's calc_dfdx/calc_dfdy in
WPS geogrid/src/process_tile_module.f90: a centred difference over two fire
cells in the interior, one-sided at the domain edges.  Where high-resolution
terrain coverage is clipped, both gradients are set to zero if this stencil
crosses the coverage boundary.

The map scale factor is applied, so the gradients stay correct on domains
large enough for it to depart appreciably from 1.  Note that the sense of the
correction here is the opposite of geogrid's: WRF measures grid spacing in
projection space and takes the true distance between grid points to be
dx/MAPFAC (dyn_em/module_diffusion_em.F builds its physical mixing length as
sqrt(dx/msftx * dy/msfty)), so a physical gradient must *multiply* by the map
factor.  geogrid's calc_dfdx divides by it instead.  Map factors are evaluated
in row chunks to avoid allocating full-domain coordinate and factor arrays.
"""

from __future__ import annotations

import numpy as np
from pyproj import CRS, Proj, Transformer

from .fire_grid import FireGrid
from .wrf_domain import WRF_SPHERE_RADIUS


#--------------------------------------------------------------------------------
# Projection scaling
#--------------------------------------------------------------------------------

def _apply_map_scale(
    dzdxf: np.ndarray,
    dzdyf: np.ndarray,
    fire_grid: FireGrid,
    apply_mask: np.ndarray | None = None,
) -> None:
    """Apply WRF-compatible map factors at fire-grid cell centres.

    For the conformal projections WRF supports, the parallel and meridional
    scales are equal to within roundoff.  They are applied separately here,
    mirroring geogrid's use of MAPFAC_MX and MAPFAC_MY.

    A geographic (lat-lon) fire grid is unchanged because its spacing is in
    degrees rather than projected metres and these metric terms do not apply.
    If *apply_mask* is supplied, projection work is limited to its bounding
    box; values outside the mask are subsequently zeroed by ``compute_slope``.
    """
    if fire_grid.crs.is_geographic:
        return

    ny, nx = dzdxf.shape
    if apply_mask is None:
        row_start, row_stop = 0, ny
        column_start, column_stop = 0, nx
    else:
        valid_rows, valid_columns = np.nonzero(apply_mask)
        if valid_rows.size == 0:
            return
        row_start, row_stop = valid_rows.min(), valid_rows.max() + 1
        column_start, column_stop = valid_columns.min(), valid_columns.max() + 1

    transform = fire_grid.transform
    # from_origin() yields an axis-aligned transform, so cell centres separate
    # into independent 1-D x and y sequences.
    columns = np.arange(column_start, column_stop)
    xs = transform.c + (columns + 0.5) * transform.a
    geographic_crs = CRS.from_proj4(
        f"+proj=longlat +a={WRF_SPHERE_RADIUS} +b={WRF_SPHERE_RADIUS} +no_defs"
    )
    transformer = Transformer.from_crs(
        fire_grid.crs, geographic_crs, always_xy=True
    )
    projection = Proj(fire_grid.crs)

    # Fire arrays use south-to-north row order. Raster transforms use the
    # opposite ordering, so select projected y coordinates from north to south.
    # Process rows in chunks to avoid full-domain lon/lat/map-factor arrays.
    chunk_rows = 256
    for start in range(row_start, row_stop, chunk_rows):
        stop = min(start + chunk_rows, row_stop)
        wrf_rows = np.arange(start, stop)
        raster_rows = ny - 1 - wrf_rows
        ys = transform.f + (raster_rows + 0.5) * transform.e
        x_grid, y_grid = np.meshgrid(xs, ys)
        lon, lat = transformer.transform(x_grid, y_grid)
        factors = projection.get_factors(lon, lat, radians=False)
        selection = (slice(start, stop), slice(column_start, column_stop))
        dzdxf[selection] *= np.asarray(factors.parallel_scale, dtype=np.float32)
        dzdyf[selection] *= np.asarray(factors.meridional_scale, dtype=np.float32)


#--------------------------------------------------------------------------------
# Finite-difference gradients
#--------------------------------------------------------------------------------

def gradient_coverage_mask(valid_mask: np.ndarray) -> np.ndarray:
    """Require valid high-resolution data over each two-dimensional stencil."""
    valid = np.asarray(valid_mask, dtype=bool)
    if valid.ndim != 2:
        raise ValueError(f"coverage mask must be two-dimensional, got {valid.shape}")
    stencil = valid.copy()
    stencil[:, 1:-1] &= valid[:, :-2] & valid[:, 2:]
    stencil[:, 0] &= valid[:, 1]
    stencil[:, -1] &= valid[:, -2]
    stencil[1:-1, :] &= valid[:-2, :] & valid[2:, :]
    stencil[0, :] &= valid[1, :]
    stencil[-1, :] &= valid[-2, :]
    return stencil


def compute_slope(
    zsf: np.ndarray,
    fire_grid: FireGrid,
    valid_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (dzdxf, dzdyf) as float32 arrays shaped like *zsf*.

    Args:
        zsf: Terrain height on the fire grid, shape (ny_fire, nx_fire),
             row 0 = southernmost (WRF/WPS netCDF order).
        fire_grid: The FireGrid the terrain was reprojected onto; supplies the
                   cell spacing and projection used for the map factor.
        valid_mask: Optional high-resolution terrain coverage. Gradients are
                    zero where their finite-difference stencil crosses its
                    boundary.

    Because row 0 is the southernmost row, axis 0 increases northward and
    axis 1 increases eastward, so both gradients are positive uphill toward
    increasing x/y, the same sign convention WRF-Fire expects.
    """
    zsf_values = np.asarray(zsf, dtype=np.float32)
    expected_shape = (fire_grid.ny_fire, fire_grid.nx_fire)
    if zsf_values.shape != expected_shape:
        raise ValueError(
            f"ZSF shape {zsf_values.shape} does not match the fire grid {expected_shape}"
        )
    if zsf_values.shape[0] < 2 or zsf_values.shape[1] < 2:
        raise ValueError(f"ZSF must be at least 2 x 2, got {zsf_values.shape}")
    if not np.isfinite(zsf_values).all():
        raise ValueError("ZSF must be finite before terrain gradients are calculated")

    dzdxf = np.empty_like(zsf_values)
    dzdyf = np.empty_like(zsf_values)
    dx_fire, dy_fire = fire_grid.dx, fire_grid.dy

    dzdxf[:, 1:-1] = (zsf_values[:, 2:] - zsf_values[:, :-2]) / (2.0 * dx_fire)
    dzdxf[:, 0] = (zsf_values[:, 1] - zsf_values[:, 0]) / dx_fire
    dzdxf[:, -1] = (zsf_values[:, -1] - zsf_values[:, -2]) / dx_fire
    dzdyf[1:-1, :] = (zsf_values[2:, :] - zsf_values[:-2, :]) / (2.0 * dy_fire)
    dzdyf[0, :] = (zsf_values[1, :] - zsf_values[0, :]) / dy_fire
    dzdyf[-1, :] = (zsf_values[-1, :] - zsf_values[-2, :]) / dy_fire

    stencil = None
    if valid_mask is not None:
        if np.asarray(valid_mask).shape != expected_shape:
            raise ValueError(
                f"coverage mask shape {np.asarray(valid_mask).shape} "
                f"does not match the fire grid {expected_shape}"
            )
        stencil = gradient_coverage_mask(valid_mask)

    _apply_map_scale(dzdxf, dzdyf, fire_grid, stencil)

    if stencil is not None:
        dzdxf[~stencil] = 0.0
        dzdyf[~stencil] = 0.0

    return dzdxf.astype(np.float32), dzdyf.astype(np.float32)
