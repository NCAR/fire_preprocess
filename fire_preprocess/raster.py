"""Read and reproject GeoTIFF files onto the WRF fire subgrid.

Two public entry points:
  reproject_fuel(src_path, fire_grid)  →  float32 array on mass grid
  reproject_dem (src_path, fire_grid)  →  float32 array on staggered grid

Both use rasterio.warp.reproject so the source raster can be in any CRS
supported by GDAL/PROJ; the transformation to the WRF map projection is
performed automatically.
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
    target: str,
    resampling: Resampling,
    band: int = 1,
    src_nodata: float = None,
    field_name: str = "field",
) -> np.ndarray:
    """Core reprojection routine.

    Args:
        src_path:   path to source GeoTIFF
        fire_grid:  FireGrid object describing the target grid
        target:     "mass" (NFUEL_CAT) or "stag" (ZSF)
        resampling: rasterio Resampling enum value
        band:       1-based band index to read from source
        src_nodata: override source nodata value (None = use raster metadata)
        field_name: used in warning messages only

    Returns:
        2-D float32 numpy array in row-major (south_north, west_east) order.
        Row 0 is the northernmost row (matching met_em convention).
    """
    if target == "mass":
        height, width = fire_grid.ny_mass, fire_grid.nx_mass
        dst_transform = fire_grid.transform_mass
    elif target == "stag":
        height, width = fire_grid.ny_stag, fire_grid.nx_stag
        dst_transform = fire_grid.transform_stag
    else:
        raise ValueError(f"target must be 'mass' or 'stag', got '{target!r}'")

    dst_crs = RasterioCRS.from_user_input(fire_grid.crs.to_wkt())
    dst_data = np.empty((height, width), dtype=np.float32)

    with rasterio.open(src_path) as src:
        nodata = src_nodata if src_nodata is not None else src.nodata
        src_data = src.read(band).astype(np.float32)

        reproject(
            source=src_data,
            destination=dst_data,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=nodata,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=resampling,
        )

    _warn_coverage(dst_data, nodata, field_name)
    return dst_data


def reproject_fuel(src_path: str, fire_grid: FireGrid, band: int = 1) -> np.ndarray:
    """Reproject a fuel-category GeoTIFF to the fire mass grid.

    Uses nearest-neighbour resampling to preserve integer category values.
    LANDFIRE categorical data must not be interpolated.
    """
    return reproject_to_grid(
        src_path, fire_grid,
        target="mass",
        resampling=Resampling.nearest,
        band=band,
        field_name="NFUEL_CAT",
    )


def reproject_dem(src_path: str, fire_grid: FireGrid, band: int = 1) -> np.ndarray:
    """Reproject a terrain DEM GeoTIFF to the fire staggered grid.

    Uses bilinear resampling, matching the WPS geogrid four_pt interpolation
    specified for ZSF in GEOGRID.TBL.FIRE.
    """
    return reproject_to_grid(
        src_path, fire_grid,
        target="stag",
        resampling=Resampling.bilinear,
        band=band,
        field_name="ZSF",
    )
