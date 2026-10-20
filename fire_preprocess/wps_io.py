"""Read and write WPS netCDF files (geo_em / met_em)."""
import os

import netCDF4 as nc
import numpy as np

FIRE_VARS = frozenset({"NFUEL_CAT", "ZSF", "DZDXF", "DZDYF"})

_DIM_SN = "south_north_subgrid"
_DIM_WE = "west_east_subgrid"


# ── Conflict detection and user prompt ───────────────────────────────────────

def check_existing_fire_vars(path: str) -> set[str]:
    """Return the set of FIRE_VARS already present in the file."""
    with nc.Dataset(path) as ds:
        return FIRE_VARS & set(ds.variables.keys())


def prompt_overwrite(path: str, existing: set[str]) -> bool:
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

def _ensure_dim(ds: nc.Dataset, name: str, size: int) -> None:
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


def _write_subgrid_var(
    ds: nc.Dataset,
    name: str,
    data: np.ndarray,
    sr_x: int,
    sr_y: int,
    description: str,
    units: str,
    overwrite: bool,
) -> None:
    ny, nx = data.shape
    _ensure_dim(ds, _DIM_SN, ny)
    _ensure_dim(ds, _DIM_WE, nx)

    if name in ds.variables:
        if not overwrite:
            raise RuntimeError(f"{name} already exists; pass overwrite=True to replace it.")
        var = ds.variables[name]
        expected_dimensions = ("Time", _DIM_SN, _DIM_WE)
        if var.dimensions != expected_dimensions:
            raise ValueError(
                f"{name} dimensions are {var.dimensions}, expected {expected_dimensions}"
            )
    else:
        var = ds.createVariable(
            name, "f4",
            ("Time", _DIM_SN, _DIM_WE),
            fill_value=False,
        )
    var.FieldType = np.int32(104)
    var.MemoryOrder = "XY "
    var.description = description
    var.units = units
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
    dzdxf: np.ndarray,
    dzdyf: np.ndarray,
    nfuel_description: str = "Fuel category for fire model",
    zsf_description: str = "Topography height",
    overwrite: bool = False,
) -> None:
    """Write static fire-grid fields into a WPS file in-place.

    All fields are written on south_north_subgrid × west_east_subgrid,
    sized (ny_mass + 1) * sr_y × (nx_mass + 1) * sr_x = e_sn*sr_y × e_we*sr_x.

    Args:
        path:              WPS netCDF file path (geo_em or met_em)
        nfuel_cat:         float32 array, shape (ny_fire, nx_fire), row 0 = southernmost
        zsf:               terrain height on the fire grid
        sr_x:              fire subgrid ratio, west-east (written as variable attribute)
        sr_y:              fire subgrid ratio, south-north (written as variable attribute)
        dzdxf:             dimensionless west-east terrain gradient
        dzdyf:             dimensionless south-north terrain gradient
        nfuel_description: written to NFUEL_CAT:description
        zsf_description:   written to ZSF:description
        overwrite:         if True, silently overwrite any existing fire variables
    """
    fields = (
        ("NFUEL_CAT", nfuel_cat, nfuel_description, ""),
        ("ZSF", zsf, zsf_description, "meters MSL"),
        ("DZDXF", dzdxf, "df/dx", "-"),
        ("DZDYF", dzdyf, "df/dy", "-"),
    )
    expected_shape = np.asarray(nfuel_cat).shape
    for name, data, _, _ in fields:
        values = np.asarray(data)
        if values.shape != expected_shape:
            raise ValueError(
                f"{name} shape {values.shape} differs from {expected_shape}"
            )
        if values.ndim != 2 or not np.isfinite(values).all():
            raise ValueError(f"{name} must be a finite two-dimensional field")

    with nc.Dataset(path, "r+") as ds:
        for name, data, description, units in fields:
            _write_subgrid_var(
                ds, name, data, sr_x, sr_y, description, units, overwrite
            )
