"""Read and write WPS netCDF files (geo_em / met_em)."""
import os

import netCDF4 as nc
import numpy as np

FIRE_VARS = frozenset({"NFUEL_CAT", "ZSF"})

_DIM_SN = "south_north_subgrid"
_DIM_WE = "west_east_subgrid"


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


def _write_nfuel_cat(ds, data: np.ndarray, sr_x: int, sr_y: int,
                     description: str, overwrite: bool):
    ny, nx = data.shape
    _ensure_dim(ds, _DIM_SN, ny)
    _ensure_dim(ds, _DIM_WE, nx)

    if "NFUEL_CAT" in ds.variables:
        if not overwrite:
            raise RuntimeError("NFUEL_CAT already exists; pass overwrite=True to replace it.")
        ds.variables["NFUEL_CAT"][0] = data
        return

    var = ds.createVariable(
        "NFUEL_CAT", "f4",
        ("Time", _DIM_SN, _DIM_WE),
        fill_value=False,
    )
    var.FieldType = np.int32(104)
    var.MemoryOrder = "XY "
    var.description = description
    var.units = ""
    var.stagger = "M"
    var.sr_x = np.int32(sr_x)
    var.sr_y = np.int32(sr_y)
    var[0] = data


def _write_zsf(ds, data: np.ndarray, sr_x: int, sr_y: int,
               description: str, overwrite: bool):
    ny, nx = data.shape
    _ensure_dim(ds, _DIM_SN, ny)
    _ensure_dim(ds, _DIM_WE, nx)

    if "ZSF" in ds.variables:
        if not overwrite:
            raise RuntimeError("ZSF already exists; pass overwrite=True to replace it.")
        ds.variables["ZSF"][0] = data
        return

    var = ds.createVariable(
        "ZSF", "f4",
        ("Time", _DIM_SN, _DIM_WE),
        fill_value=False,
    )
    var.FieldType = np.int32(104)
    var.MemoryOrder = "XY "
    var.description = description
    var.units = "meters MSL"
    var.stagger = "M"
    var.sr_x = np.int32(sr_x)
    var.sr_y = np.int32(sr_y)
    var[0] = data


# ── Public write function ─────────────────────────────────────────────────────

def write_fire_vars(
    path: str,
    nfuel_cat: np.ndarray,
    zsf: np.ndarray,
    sr_x: int,
    sr_y: int,
    nfuel_description: str = "Fuel category for fire model",
    zsf_description: str = "Topography height",
    overwrite: bool = False,
) -> None:
    """Write NFUEL_CAT and ZSF into a WPS netCDF file, modifying it in-place.

    Both variables are written on south_north_subgrid × west_east_subgrid,
    sized (ny_mass + 1) * sr_y × (nx_mass + 1) * sr_x = e_sn*sr_y × e_we*sr_x.

    Args:
        path:              WPS netCDF file path (geo_em or met_em)
        nfuel_cat:         float32 array, shape (ny_fire, nx_fire), row 0 = southernmost
        zsf:               float32 array, shape (ny_fire, nx_fire), row 0 = southernmost
        sr_x:              fire subgrid ratio, west-east (written as variable attribute)
        sr_y:              fire subgrid ratio, south-north (written as variable attribute)
        nfuel_description: written to NFUEL_CAT:description
        zsf_description:   written to ZSF:description
        overwrite:         if True, silently overwrite any existing fire variables
    """
    with nc.Dataset(path, "r+") as ds:
        _write_nfuel_cat(ds, nfuel_cat, sr_x, sr_y, nfuel_description, overwrite)
        _write_zsf(ds, zsf, sr_x, sr_y, zsf_description, overwrite)
