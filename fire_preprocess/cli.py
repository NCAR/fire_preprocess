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

# Maps config.yaml keys → argparse dest names.
# Supports both underscore and hyphen variants for convenience.
_CONFIG_KEY_MAP = {
    "met_files":  "met_em",
    "met_em":     "met_em",
    "ZSF":        "dem",
    "dem":        "dem",
    "fuel":       "fuel",
    "namelist":   "namelist",
    "fuel_table": "fuel_table",
    "fuel-table": "fuel_table",
    "domain":     "domain",
    "overwrite":  "yes",
}

_REQUIRED = ("met_em", "fuel", "dem", "namelist")


def load_config(path: str) -> dict:
    """Load a YAML config file and return a dict keyed by argparse dest names."""
    with open(path) as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ValueError(f"Config file '{path}' must contain a YAML mapping at the top level.")

    cfg = {}
    unknown = []
    for key, value in raw.items():
        dest = _CONFIG_KEY_MAP.get(key)
        if dest is None:
            unknown.append(key)
        else:
            cfg[dest] = value

    if unknown:
        print(f"Warning: unrecognised config key(s) ignored: {', '.join(unknown)}", file=sys.stderr)

    return cfg


def _merge(args: argparse.Namespace, cfg: dict) -> argparse.Namespace:
    """Apply config values for any arg that was not set explicitly on the CLI.

    Precedence (highest → lowest): CLI flag  >  config file  >  argparse default.

    argparse stores the default for store_true flags as False and for optional
    string args as None, so we treat False / None as "not set by the user".
    """
    for dest, value in cfg.items():
        current = getattr(args, dest, None)
        if dest == "yes":
            # Only apply config's overwrite=True if --yes was not passed
            if not current:
                setattr(args, dest, bool(value))
        elif dest == "domain":
            # domain has a non-None default (1); only override if still at default
            # and config provides an explicit value
            if current == 1 and value is not None:
                setattr(args, dest, int(value))
        elif dest == "fuel_table":
            if current == "fbfm13":  # argparse default; override with config value
                setattr(args, dest, str(value))
        else:
            if current is None:
                setattr(args, dest, str(value) if value is not None else None)
    return args


def build_parser() -> argparse.ArgumentParser:
    config_example = (
        "  met_files: 'met_em.d01.*.nc'\n"
        "  ZSF:       /path/to/highres_dem.tif\n"
        "  fuel:      /path/to/landfire.tif\n"
        "  namelist:  namelist.wps\n"
        "  fuel_table: fbfm13\n"
        "  domain:    1\n"
        "  overwrite: false\n"
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
            "  fire_preprocess --met-em /path/to/WPS/ --fuel landfire.tif \\\n"
            "                  --dem dem.tif --namelist namelist.wps\n\n"
            "Example (config file):\n"
            "  fire_preprocess --config fire_preprocess.yaml\n"
        ),
    )
    parser.add_argument(
        "-c", "--config", metavar="FILE",
        help="YAML config file; any key can be overridden by a CLI flag",
    )
    parser.add_argument(
        "--met-em", default=None, metavar="PATH",
        help=(
            "Path to a met_em file, directory, or glob pattern "
            "(config key: met_files)"
        ),
    )
    parser.add_argument(
        "--fuel", default=None, metavar="GEOTIFF",
        help="LANDFIRE fuel-category GeoTIFF (NFUEL_CAT source)",
    )
    parser.add_argument(
        "--dem", default=None, metavar="GEOTIFF",
        help="High-resolution terrain DEM GeoTIFF (ZSF source; config key: ZSF)",
    )
    parser.add_argument(
        "--namelist", default=None, metavar="FILE",
        help="Path to namelist.wps (provides subgrid_ratio_x/y and projection parameters)",
    )
    parser.add_argument(
        "--fuel-table", default="fbfm13", metavar="NAME|PATH",
        help=(
            f"Fuel remapping table: built-in name or CSV path. "
            f"Default: fbfm13. Available: {', '.join(list_fuel_tables())}"
        ),
    )
    parser.add_argument(
        "--domain", type=int, default=1, metavar="N",
        help="Domain number used when searching a directory for met_em files. Default: 1",
    )
    parser.add_argument(
        "-y", "--yes", action="store_true",
        help="Overwrite existing NFUEL_CAT/ZSF variables without prompting (config key: overwrite)",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    # ── Load and merge config file ────────────────────────────────────────────
    if args.config:
        cfg = load_config(args.config)
        args = _merge(args, cfg)

    # ── Validate required arguments ───────────────────────────────────────────
    missing = [f"--{d.replace('_', '-')}" for d in _REQUIRED if not getattr(args, d, None)]
    if missing:
        parser.error(
            f"The following arguments are required: {', '.join(missing)}\n"
            "Supply them on the command line or via --config."
        )

    # ── Find met_em files ─────────────────────────────────────────────────────
    print(f"Searching for met_em files: {args.met_em}")
    met_em_files = find_met_em_files(args.met_em, domain=args.domain)
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
    print(f"Reprojecting terrain DEM: {args.dem}")
    zsf = reproject_dem(args.dem, fire_grid)
    print(
        f"  ZSF shape {zsf.shape}  "
        f"range [{zsf.min():.1f}, {zsf.max():.1f}] m"
    )

    # ── Write to met_em files ─────────────────────────────────────────────────
    skipped = 0
    for met_em_path in met_em_files:
        label = os.path.basename(met_em_path)
        existing = check_existing_fire_vars(met_em_path)
        overwrite = args.yes

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
