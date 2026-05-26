"""Read and reproject GeoTIFF files onto the WRF fire subgrid.

Two public entry points:
  reproject_fuel(src_path, fire_grid)  →  float32 array (NFUEL_CAT)
  reproject_dem (src_path, fire_grid)  →  float32 array (ZSF)

Both map onto the same fire grid (south_north_subgrid × west_east_subgrid).
rasterio.warp.reproject handles the CRS transformation from the source
raster's native projection to the WRF map projection automatically.
"""
import warnings
import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling
from rasterio.crs import CRS as RasterioCRS

from .fire_grid import FireGrid


def _warn_coverage(arr, nodata_val, field_name, threshold=0.05):
    """Emit a warning if more than *threshold* fraction of pixels are nodata."""
    if nodata_val is None:
        return
    mask = (arr == nodata_val) | np.isnan(arr)
    frac = mask.sum() / arr.size
    if frac > threshold:
        warnings.warn(
            f"{field_name}: {frac:.1%} of fire-grid pixels are nodata — "
            "check that the source raster covers the full WRF domain.",
            stacklevel=3,
        )


def reproject_to_grid(
    src_path: str,
    fire_grid: FireGrid,
    resampling: Resampling,
    band: int = 1,
    src_nodata: float = None,
    field_name: str = "field",
) -> np.ndarray:
    """Core reprojection routine.

    Returns a 2-D float32 array in WRF row order (south_north, west_east):
    row 0 is the *southernmost* row, matching WRF/WPS netCDF convention.
    """
    height, width = fire_grid.ny_fire, fire_grid.nx_fire
    dst_crs = RasterioCRS.from_user_input(fire_grid.crs.to_wkt())

    # np.zeros ensures any pixels rasterio does not write (e.g. at domain
    # edges outside the source extent) get a known value rather than garbage.
    dst_data = np.zeros((height, width), dtype=np.float32)

    with rasterio.open(src_path) as src:
        nodata = src_nodata if src_nodata is not None else src.nodata
        src_data = src.read(band).astype(np.float32)

        reproject(
            source=src_data,
            destination=dst_data,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=nodata,
            dst_transform=fire_grid.transform,
            dst_crs=dst_crs,
            resampling=resampling,
        )

    # rasterio returns row 0 = north; WRF netCDF expects row 0 = south.
    dst_data = np.flipud(dst_data)

    _warn_coverage(dst_data, nodata, field_name)
    return dst_data


def reproject_fuel(src_path: str, fire_grid: FireGrid, band: int = 1) -> np.ndarray:
    """Reproject a fuel-category GeoTIFF to the fire grid.

    Uses nearest-neighbour resampling to preserve integer category values.
    LANDFIRE categorical data must not be interpolated.
    """
    return reproject_to_grid(
        src_path, fire_grid,
        resampling=Resampling.nearest,
        band=band,
        field_name="NFUEL_CAT",
    )


def reproject_dem(src_path: str, fire_grid: FireGrid, band: int = 1) -> np.ndarray:
    """Reproject a terrain DEM GeoTIFF to the fire grid.

    Uses bilinear resampling, matching the WPS geogrid four_pt interpolation
    specified for ZSF in GEOGRID.TBL.FIRE.
    """
    return reproject_to_grid(
        src_path, fire_grid,
        resampling=Resampling.bilinear,
        band=band,
        field_name="ZSF",
    )
