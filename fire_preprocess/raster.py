"""Read and reproject GeoTIFF files onto the WRF fire subgrid.

Two public entry points:
  reproject_fuel(src_path, fire_grid)  →  float32 array (NFUEL_CAT)
  reproject_dem (src_path, fire_grid)  →  float32 array (ZSF)

Both can optionally return a Boolean source-coverage mask with the field.
Both map onto the same fire grid (south_north_subgrid × west_east_subgrid).
rasterio.warp.reproject handles the CRS transformation from the source
raster's native projection to the WRF map projection automatically.
"""

from __future__ import annotations

import warnings

import numpy as np
import rasterio
from rasterio.crs import CRS as RasterioCRS
from rasterio.warp import Resampling, reproject

from .fire_grid import FireGrid


def _warn_coverage(
    valid_mask: np.ndarray,
    field_name: str,
    threshold: float = 0.05,
) -> None:
    """Report substantial gaps without treating clipped rasters as an error."""
    frac = 1.0 - np.count_nonzero(valid_mask) / valid_mask.size
    if frac > threshold:
        warnings.warn(
            f"{field_name}: {frac:.1%} of fire-grid pixels are outside the "
            "source coverage; the workflow will use its configured background.",
            stacklevel=3,
        )


def reproject_to_grid(
    src_path: str,
    fire_grid: FireGrid,
    resampling: Resampling,
    band: int = 1,
    src_nodata: float | None = None,
    field_name: str = "field",
    return_mask: bool = False,
) -> np.ndarray | tuple[np.ndarray, np.ndarray]:
    """Core reprojection routine.

    Returns a 2-D float32 array in WRF row order (south_north, west_east):
    row 0 is the *southernmost* row, matching WRF/WPS netCDF convention.
    """
    height, width = fire_grid.ny_fire, fire_grid.nx_fire
    dst_crs = RasterioCRS.from_user_input(fire_grid.crs.to_wkt())

    # NaN ensures pixels rasterio does not write, including domain areas
    # outside the source extent, are represented explicitly in the mask.
    dst_data = np.full((height, width), np.nan, dtype=np.float32)

    with rasterio.open(src_path) as src:
        nodata = src_nodata if src_nodata is not None else src.nodata
        src_data = src.read(band).astype(np.float32)

        reproject(
            source=src_data,
            destination=dst_data,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=nodata,
            dst_nodata=np.nan,
            dst_transform=fire_grid.transform,
            dst_crs=dst_crs,
            resampling=resampling,
            init_dest_nodata=True,
        )

    # rasterio returns row 0 = north; WRF netCDF expects row 0 = south.
    dst_data = np.flipud(dst_data)
    valid_mask = np.isfinite(dst_data)

    _warn_coverage(valid_mask, field_name)
    if return_mask:
        return dst_data, valid_mask
    return dst_data


def reproject_fuel(
    src_path: str,
    fire_grid: FireGrid,
    band: int = 1,
    return_mask: bool = False,
) -> np.ndarray | tuple[np.ndarray, np.ndarray]:
    """Reproject a fuel-category GeoTIFF to the fire grid.

    Uses nearest-neighbour resampling to preserve integer category values.
    LANDFIRE categorical data must not be interpolated.
    """
    return reproject_to_grid(
        src_path, fire_grid,
        resampling=Resampling.nearest,
        band=band,
        field_name="NFUEL_CAT", return_mask=return_mask,
    )


def reproject_dem(
    src_path: str,
    fire_grid: FireGrid,
    band: int = 1,
    return_mask: bool = False,
) -> np.ndarray | tuple[np.ndarray, np.ndarray]:
    """Reproject a terrain DEM GeoTIFF to the fire grid.

    Uses bilinear resampling, matching the WPS geogrid four_pt interpolation
    specified for ZSF in GEOGRID.TBL.FIRE.
    """
    return reproject_to_grid(
        src_path, fire_grid,
        resampling=Resampling.bilinear,
        band=band,
        field_name="ZSF", return_mask=return_mask,
    )
