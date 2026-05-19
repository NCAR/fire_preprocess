"""Command-line interface for fire_preprocess."""
import argparse
import os
import sys

import yaml

from .namelist import get_fire_subgrid_ratios, get_domain_params
from .wrf_domain import read_domain_from_met_em
from .fire_grid import build_fire_grid
from .raster import reproject_fuel, reproject_dem
from .fuel_tables import get_fuel_table, list_fuel_tables
from .met_em_io import find_met_em_files, check_existing_fire_vars, prompt_overwrite, write_fire_vars

_REQUIRED = ("met_files", "zsf", "fuel", "namelist")

# Defaults applied after CLI + config are merged, so neither source
# can be mistaken for an explicit user value.
_DEFAULTS = {
    "fuel_table": "fbfm13",
    "domain": 1,
    "overwrite": False,
}


def load_config(path: str) -> dict:
    """Load a YAML config file and return a dict keyed by argparse dest names.

    Config keys are normalised to lowercase with hyphens replaced by
    underscores, so 'ZSF', 'zsf', and 'z-s-f' all map to dest 'zsf'.
    """
    with open(path) as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError(f"Config file '{path}' must contain a YAML mapping at the top level.")

    cfg = {}
    for key, value in raw.items():
        dest = key.lower().replace("-", "_")
        cfg[dest] = value
    return cfg


def _merge(args: argparse.Namespace, cfg: dict) -> argparse.Namespace:
    """Fill None / unset args from config, then apply hardcoded defaults.

    Precedence (highest → lowest): CLI flag > config file > _DEFAULTS.
    """
    for dest, value in cfg.items():
        current = getattr(args, dest, None)
        if dest == "overwrite":
            if not current:
                setattr(args, dest, bool(value))
        elif current is None:
            setattr(args, dest, value)

    for dest, default in _DEFAULTS.items():
        if getattr(args, dest, None) is None:
            setattr(args, dest, default)

    return args


def build_parser() -> argparse.ArgumentParser:
    config_example = (
        "  met_files:  'met_em.d01.*.nc'\n"
        "  zsf:        /path/to/highres_dem.tif\n"
        "  fuel:       /path/to/landfire.tif\n"
        "  namelist:   namelist.wps\n"
        "  fuel_table: fbfm13\n"
        "  domain:     1\n"
        "  overwrite:  false\n"
    )
    parser = argparse.ArgumentParser(
        prog="fire_preprocess",
        description=(
            "Add WRF-FIRE fields (NFUEL_CAT, ZSF) directly to met_em netCDF files,\n"
            "bypassing GEOGRID.TBL editing and geogrid binary format conversion."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            f"Built-in fuel tables: {', '.join(list_fuel_tables())}\n\n"
            "Config file keys (YAML):\n"
            f"{config_example}\n"
            "CLI flags override config file values when both are supplied.\n\n"
            "Example (CLI only):\n"
            "  fire_preprocess --met-files 'met_em.d01.*.nc' --fuel landfire.tif \\\n"
            "                  --zsf dem.tif --namelist namelist.wps\n\n"
            "Example (config file):\n"
            "  fire_preprocess --config config.yaml\n"
        ),
    )
    parser.add_argument(
        "-c", "--config", metavar="FILE",
        help="YAML config file; any key can be overridden by a CLI flag",
    )
    parser.add_argument(
        "--met-files", default=None, metavar="PATH", dest="met_files",
        help="Path to a met_em file, directory, or glob pattern",
    )
    parser.add_argument(
        "--zsf", default=None, metavar="GEOTIFF",
        help="High-resolution terrain DEM GeoTIFF (ZSF source; ≥1/3 arc-sec recommended)",
    )
    parser.add_argument(
        "--fuel", default=None, metavar="GEOTIFF",
        help="LANDFIRE fuel-category GeoTIFF (NFUEL_CAT source)",
    )
    parser.add_argument(
        "--namelist", default=None, metavar="FILE",
        help="Path to namelist.wps (provides subgrid_ratio_x/y and projection parameters)",
    )
    parser.add_argument(
        "--fuel-table", default=None, metavar="NAME|PATH", dest="fuel_table",
        help=(
            f"Fuel remapping table: built-in name or CSV path. "
            f"Default: fbfm13. Available: {', '.join(list_fuel_tables())}"
        ),
    )
    parser.add_argument(
        "--domain", type=int, default=None, metavar="N",
        help="Domain number used when searching a directory for met_em files. Default: 1",
    )
    parser.add_argument(
        "--overwrite", action="store_true", default=False,
        help="Overwrite existing NFUEL_CAT/ZSF variables without prompting",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    # ── Load config and merge ─────────────────────────────────────────────────
    cfg = load_config(args.config) if args.config else {}
    args = _merge(args, cfg)

    # ── Validate required arguments ───────────────────────────────────────────
    missing = [f"--{d.replace('_', '-')}" for d in _REQUIRED if not getattr(args, d, None)]
    if missing:
        parser.error(
            f"The following arguments are required: {', '.join(missing)}\n"
            "Supply them on the command line or via --config."
        )

    # ── Find met_em files ─────────────────────────────────────────────────────
    print(f"Searching for met_em files: {args.met_files}")
    met_em_files = find_met_em_files(args.met_files, domain=args.domain)
    basenames = [os.path.basename(f) for f in met_em_files]
    print(f"  Found {len(met_em_files)} file(s): {basenames}")

    # ── Read namelist ─────────────────────────────────────────────────────────
    print(f"Reading namelist: {args.namelist}")
    sr_x, sr_y = get_fire_subgrid_ratios(args.namelist)
    print(f"  subgrid_ratio_x = {sr_x},  subgrid_ratio_y = {sr_y}")
    nml_params = get_domain_params(args.namelist)

    # ── Build WRF domain geometry ─────────────────────────────────────────────
    print(f"Reading domain geometry from {basenames[0]} ...")
    domain = read_domain_from_met_em(met_em_files[0], sr_x, sr_y, namelist_params=nml_params)
    print(
        f"  Atmospheric grid : {domain.nx} × {domain.ny} mass pts  "
        f"dx={domain.dx:.1f} m  dy={domain.dy:.1f} m"
    )

    fire_grid = build_fire_grid(domain)
    print(
        f"  Fire mass grid   : {fire_grid.nx_mass} × {fire_grid.ny_mass}  "
        f"({fire_grid.dx:.1f} m × {fire_grid.dy:.1f} m cells)"
    )
    print(f"  Fire stag grid   : {fire_grid.nx_stag} × {fire_grid.ny_stag}")

    # ── Load fuel table ───────────────────────────────────────────────────────
    fuel_table = get_fuel_table(args.fuel_table)
    print(f"Fuel table: {fuel_table.name}  —  {fuel_table.description}")

    # ── Reproject fuel categories ─────────────────────────────────────────────
    print(f"Reprojecting fuel data: {args.fuel}")
    nfuel_raw = reproject_fuel(args.fuel, fire_grid)
    nfuel = fuel_table.apply(nfuel_raw)
    print(
        f"  NFUEL_CAT shape {nfuel.shape}  "
        f"range [{int(nfuel.min())}, {int(nfuel.max())}]"
    )

    # ── Reproject DEM ─────────────────────────────────────────────────────────
    print(f"Reprojecting terrain DEM: {args.zsf}")
    zsf = reproject_dem(args.zsf, fire_grid)
    print(
        f"  ZSF shape {zsf.shape}  "
        f"range [{zsf.min():.1f}, {zsf.max():.1f}] m"
    )

    # ── Write to met_em files ─────────────────────────────────────────────────
    skipped = 0
    for met_em_path in met_em_files:
        label = os.path.basename(met_em_path)
        existing = check_existing_fire_vars(met_em_path)
        overwrite = args.overwrite

        if existing and not overwrite:
            overwrite = prompt_overwrite(met_em_path, existing)
            if not overwrite:
                print(f"  Skipped {label}.")
                skipped += 1
                continue

        print(f"  Writing {label} ... ", end="", flush=True)
        write_fire_vars(met_em_path, nfuel, zsf, overwrite=overwrite)
        print("done.")

    written = len(met_em_files) - skipped
    print(f"\nFinished: {written} file(s) updated, {skipped} skipped.")
    if written == 0:
        sys.exit(1)
