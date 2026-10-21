"""Copy fire fields from one WPS/WRF netCDF file to another.

For files that already describe the same fire grid but lack its fields --
e.g. the wrfinput_d02 written by WRF's ndown.exe, which does not carry
NFUEL_CAT, ZSF, DZDXF or DZDYF over from its fine-grid template
(wrfndi_d02). The fields are copied unchanged; nothing is reprojected, so
both files must be on the same grid, which is checked first.
"""
import netCDF4 as nc
import numpy as np

from .wps_io import FIRE_VARS, _DIM_SN, _DIM_WE, _ensure_dim

# Mass-grid coordinates: WPS files (geo_em, met_em) / WRF files (wrfinput, wrfout).
_LATLON = (("XLAT_M", "XLONG_M"), ("XLAT", "XLONG"))
_LATLON_TOL = 1e-4      # degrees, ~10 m


def _latlon(ds):
    for lat, lon in _LATLON:
        if lat in ds.variables and lon in ds.variables:
            return np.asarray(ds.variables[lat][0]), np.asarray(ds.variables[lon][0])
    return None


def check_same_grid(src, dst, names) -> None:
    """Raise ValueError unless src and dst are the same fire grid: same
    subgrid dimensions for every field, same DX/DY, and the same mass-grid
    latitudes and longitudes where both files have them."""
    for name in names:
        if name not in src.variables:
            raise ValueError(f"{name} is not in the source file")
        shape = src.variables[name].shape[-2:]
        dst_shape = (len(dst.dimensions[_DIM_SN]) if _DIM_SN in dst.dimensions else None,
                     len(dst.dimensions[_DIM_WE]) if _DIM_WE in dst.dimensions else None)
        if None not in dst_shape and dst_shape != shape:
            raise ValueError(f"fire grid differs: source {name} is {shape[0]} x {shape[1]}, "
                             f"the target's subgrid is {dst_shape[0]} x {dst_shape[1]}")
    for attr in ("DX", "DY"):
        a = getattr(src, attr, None)
        b = getattr(dst, attr, None)
        if a is not None and b is not None and abs(float(a) - float(b)) > 1e-3:
            raise ValueError(f"grid spacing differs: source {attr} = {a}, target {attr} = {b}")
    s, d = _latlon(src), _latlon(dst)
    if s is not None and d is not None:
        if s[0].shape != d[0].shape:
            raise ValueError(f"atmospheric grid differs: source is {s[0].shape}, "
                             f"target is {d[0].shape}")
        diff = max(float(np.abs(s[0] - d[0]).max()), float(np.abs(s[1] - d[1]).max()))
        if diff > _LATLON_TOL:
            raise ValueError(f"grids are in different places: lat/lon differ by up to "
                             f"{diff:.4f} degrees")


def copy_fire_vars(src_path: str, dst_path: str, names=tuple(sorted(FIRE_VARS))) -> dict:
    """Copy the named fire fields from src_path into dst_path, in place.

    A field the target already has keeps the target's own attributes (so a
    WRF file keeps WRF's metadata) and only its values are replaced. A field
    it lacks is created with the source's attributes. Returns
    {name: (min, max)} of what was written.
    """
    written = {}
    with nc.Dataset(src_path) as src, nc.Dataset(dst_path, "r+") as dst:
        check_same_grid(src, dst, names)
        for name in names:
            sv = src.variables[name]
            data = np.asarray(sv[0])
            if name in dst.variables:
                dst.variables[name][0] = data
            else:
                ny, nx = data.shape
                _ensure_dim(dst, _DIM_SN, ny)
                _ensure_dim(dst, _DIM_WE, nx)
                dv = dst.createVariable(name, sv.dtype, ("Time", _DIM_SN, _DIM_WE),
                                        fill_value=False)
                dv.setncatts({k: sv.getncattr(k) for k in sv.ncattrs() if k != "_FillValue"})
                dv[0] = data
            written[name] = (float(data.min()), float(data.max()))
    return written
