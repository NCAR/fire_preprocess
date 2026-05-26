"""Read and write WRF met_em netCDF files.

Convention note — ZSF dimension names:
  WRF-FIRE's Registry defines ZSF on the *staggered* fire grid
  (ifire_stag, one extra point per direction vs the mass grid).
  The dimension names used here match what WPS geogrid writes:
    south_north_subgrid      / west_east_subgrid       (mass,    NFUEL_CAT)
    south_north_subgrid_stag / west_east_subgrid_stag  (stagger, ZSF)
  If your WPS version uses different names, adjust _DIM_STAG_SN / _DIM_STAG_WE.
"""
import os
from typing import List

import netCDF4 as nc
import numpy as np

FIRE_VARS = frozenset({"NFUEL_CAT", "ZSF"})

_DIM_MASS_SN = "south_north_subgrid"
_DIM_MASS_WE = "west_east_subgrid"
_DIM_STAG_SN = "south_north_subgrid_stag"
_DIM_STAG_WE = "west_east_subgrid_stag"


# ── Conflict detection and user prompt ───────────────────────────────────────

def check_existing_fire_vars(path: str) -> set:
    """Return the set of FIRE_VARS already present in the file."""
    with nc.Dataset(path) as ds:
        return FIRE_VARS & set(ds.variables.keys())


def prompt_overwrite(path: str, existing: set) -> bool:
    """Interactively ask whether to overwrite existing fire variables."""
    print(
        f"\nWarning: '{os.path.basename(path)}' already contains: "
        f"{', '.join(sorted(existing))}"
    )
    while True:
        answer = input("  Overwrite? [y/N] ").strip().lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("", "n", "no"):
            return False
        print("  Please enter 'y' or 'n'.")


# ── netCDF write helpers ──────────────────────────────────────────────────────

def _ensure_dim(ds, name, size):
    if name not in ds.dimensions:
        ds.createDimension(name, size)
    else:
        existing = len(ds.dimensions[name])
        if existing != size:
            raise ValueError(
                f"Dimension '{name}' already exists with size {existing}, "
                f"but the fire grid requires size {size}. "
                "Check that namelist.wps subgrid_ratio_x/y match those used "
                "when geogrid was originally run."
            )


def _write_nfuel_cat(ds, data: np.ndarray, overwrite: bool):
    ny, nx = data.shape
    _ensure_dim(ds, _DIM_MASS_SN, ny)
    _ensure_dim(ds, _DIM_MASS_WE, nx)

    if "NFUEL_CAT" in ds.variables:
        if not overwrite:
            raise RuntimeError("NFUEL_CAT already exists; pass overwrite=True to replace it.")
        ds.variables["NFUEL_CAT"][0] = data
        return

    var = ds.createVariable(
        "NFUEL_CAT", "f4",
        ("Time", _DIM_MASS_SN, _DIM_MASS_WE),
        fill_value=False,
    )
    var.FieldType = 104
    var.MemoryOrder = "XY "
    var.description = "VEGETATION CATEGORY FOR FIRE MODEL"
    var.units = ""
    var.stagger = ""
    var.coordinates = "XLONG_M XLAT_M"
    var[0] = data


def _write_zsf(ds, data: np.ndarray, overwrite: bool):
    ny, nx = data.shape
    _ensure_dim(ds, _DIM_STAG_SN, ny)
    _ensure_dim(ds, _DIM_STAG_WE, nx)

    if "ZSF" in ds.variables:
        if not overwrite:
            raise RuntimeError("ZSF already exists; pass overwrite=True to replace it.")
        ds.variables["ZSF"][0] = data
        return

    var = ds.createVariable(
        "ZSF", "f4",
        ("Time", _DIM_STAG_SN, _DIM_STAG_WE),
        fill_value=False,
    )
    var.FieldType = 104
    var.MemoryOrder = "XY "
    var.description = "TERRAIN HEIGHT FOR FIRE MODEL"
    var.units = "m"
    var.stagger = ""
    var.coordinates = "XLONG_M XLAT_M"
    var[0] = data


# ── Public write function ─────────────────────────────────────────────────────

def write_fire_vars(
    path: str,
    nfuel_cat: np.ndarray,
    zsf: np.ndarray,
    overwrite: bool = False,
) -> None:
    """Write NFUEL_CAT and ZSF into a met_em file, modifying it in-place.

    Args:
        path:       met_em netCDF file path
        nfuel_cat:  float32 array, shape (ny_mass, nx_mass), row 0 = northernmost
        zsf:        float32 array, shape (ny_stag, nx_stag), row 0 = northernmost
        overwrite:  if True, silently overwrite any existing fire variables
    """
    with nc.Dataset(path, "r+") as ds:
        _write_nfuel_cat(ds, nfuel_cat, overwrite)
        _write_zsf(ds, zsf, overwrite)
