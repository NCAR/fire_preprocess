"""Command-line interface for fire_preprocess."""
import argparse
import glob
import os
import sys

import yaml

from .namelist import get_fire_subgrid_ratios, get_domain_params
from .wrf_domain import read_domain_from_file, read_subgrid_ratios_from_file
from .fire_grid import build_fire_grid
from .raster import reproject_fuel, reproject_dem
from .fuel_tables import get_fuel_table, list_fuel_tables
from .wps_io import check_existing_fire_vars, prompt_overwrite, write_fire_vars

_REQUIRED = ("wps_files",)

# Defaults applied after CLI + config are merged, so neither source
# can be mistaken for an explicit user value.
_DEFAULTS = {
    "fuel_table": "fbfm13",
    "domain": 1,
    "namelist": "namelist.wps",
    "overwrite": False,
    "zsf_source": "nationalmap",
    "download_dir": "downloads",
    "zsf_fill": 0.0,
}

# LANDFIRE product to download when --fuel is omitted, keyed by fuel table.
_FUEL_TABLE_PRODUCT = {
    "fbfm13": "FBFM13",
    "fbfm40": "FBFM40",
    "fbfm40_to_anderson13": "FBFM40",
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
        "  wps_files:  'met_em.d01.*.nc'\n"
        "  zsf:        /path/to/highres_dem.tif   # omit to download automatically\n"
        "  fuel:       /path/to/landfire.tif      # omit to download automatically\n"
        "  namelist:   namelist.wps\n"
        "  fuel_table: fbfm13\n"
        "  domain:     1\n"
        "  overwrite:  false\n"
        "  zsf_source: nationalmap\n"
        "  email:      you@example.org           # required for LANDFIRE downloads\n"
        "  download_dir: downloads\n"
        "  zsf_fill:   0                         # value for missing elevation pixels\n"
    )
    parser = argparse.ArgumentParser(
        prog="fire_preprocess",
        description=(
            "Add CFBM fire fields (NFUEL_CAT, ZSF) directly to WPS netCDF files,\n"
            "bypassing GEOGRID.TBL editing and geogrid binary format conversion."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            f"Built-in fuel tables: {', '.join(list_fuel_tables())}\n\n"
            "Config file keys (YAML):\n"
            f"{config_example}\n"
            "CLI flags override config file values when both are supplied.\n\n"
            "Example (CLI only):\n"
            "  fire_preprocess --wps-files 'met_em.d01.*.nc' --fuel landfire.tif \\\n"
            "                  --zsf dem.tif --namelist namelist.wps\n\n"
            "Example (config file):\n"
            "  fire_preprocess --config config.yaml\n"
        ),
    )
    parser.add_argument(
        "-c", "--config", metavar="FILE", default="config.yaml",
        help="YAML config file; any key can be overridden by a CLI flag",
    )
    parser.add_argument(
        "--wps-files", default=None, metavar="PATH", dest="wps_files",
        help="Path to a WPS output file (geo_em/met_em) or a glob pattern (e.g. 'met_em.d01.*.nc')",
    )
    parser.add_argument(
        "--zsf", default=None, metavar="GEOTIFF",
        help=(
            "High-resolution terrain DEM GeoTIFF (ZSF source; ≥1/3 arc-sec recommended). "
            "If omitted, the DEM is downloaded automatically (see --zsf-source)."
        ),
    )
    parser.add_argument(
        "--fuel", default=None, metavar="GEOTIFF",
        help=(
            "LANDFIRE fuel-category GeoTIFF (NFUEL_CAT source). If omitted, the fuel "
            "layer matching --fuel-table is downloaded automatically from LANDFIRE."
        ),
    )
    parser.add_argument(
        "--namelist", default=None, metavar="FILE",
        help=(
            "Path to namelist.wps. Optional: subgrid_ratio_x/y are read from the WPS "
            "file's sr_x/sr_y global attributes when the namelist is absent."
        ),
    )
    parser.add_argument(
        "--zsf-source", default=None, choices=("nationalmap", "landfire"), dest="zsf_source",
        help=(
            "Source for automatic ZSF download: 'nationalmap' = USGS 3DEP 1/3 arc-sec "
            "(~10 m, default), 'landfire' = LANDFIRE elevation (30 m, smaller download)"
        ),
    )
    parser.add_argument(
        "--email", default=None, metavar="ADDRESS",
        help="Email address, required by the LANDFIRE Product Service for downloads",
    )
    parser.add_argument(
        "--landfire-version", default=None, metavar="LFxxxx", dest="landfire_version",
        help=(
            "Pin the LANDFIRE version for downloaded fuel data (e.g. LF2023). "
            "Default: newest version with full geographic coverage"
        ),
    )
    parser.add_argument(
        "--download-dir", default=None, metavar="DIR", dest="download_dir",
        help="Directory where downloaded rasters are cached. Default: ./downloads",
    )
    parser.add_argument(
        "--zsf-fill", type=float, default=None, metavar="VALUE", dest="zsf_fill",
        help=(
            "Value assigned to ZSF pixels with no source elevation data "
            "(outside the DEM's extent, or nodata voids within it). Default: 0"
        ),
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
        help="Domain number used when reading namelist values. Default: 1",
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
    cfg = load_config(args.config) if args.config and os.path.isfile(args.config) else {}
    args = _merge(args, cfg)

    # ── Validate required arguments ───────────────────────────────────────────
    missing = [f"--{d.replace('_', '-')}" for d in _REQUIRED if not getattr(args, d, None)]
    if missing:
        parser.error(
            f"The following arguments are required: {', '.join(missing)}\n"
            "Supply them on the command line or via --config."
        )
    if args.zsf_source not in ("nationalmap", "landfire"):
        parser.error(f"zsf_source must be 'nationalmap' or 'landfire', got '{args.zsf_source}'")

    # ── Find WPS files ─────────────────────────────────────────────────────
    print(f"Searching for WPS file(s): {args.wps_files}")
    files = sorted(glob.glob(args.wps_files))
    if not files:
        raise FileNotFoundError(f"No files matched the pattern: '{args.wps_files}'")
    basenames = [os.path.basename(f) for f in files]
    print(f"  Found {len(files)} file(s): {basenames}")

    # ── Determine fire subgrid ratios and domain parameters ──────────────────
    # An explicit namelist value wins (e.g. adding a fire grid to a geo_em file
    # generated without one); otherwise the WPS file's sr_x/sr_y attributes are used.
    domain_index = args.domain - 1  # namelist arrays are 0-indexed, domain numbers are 1-indexed
    file_sr = read_subgrid_ratios_from_file(files[0])
    nml_sr = (None, None)
    nml_params = None
    if os.path.isfile(args.namelist):
        print(f"Reading namelist: {args.namelist}")
        nml_sr = get_fire_subgrid_ratios(args.namelist, domain_index=domain_index)
        nml_params = get_domain_params(args.namelist, domain_index=domain_index)

    if nml_sr[0] is not None:
        sr_x, sr_y = nml_sr
        sr_source = args.namelist
        if file_sr[0] is not None and file_sr != nml_sr:
            print(
                f"  Note: {basenames[0]} has sr_x/sr_y = {file_sr[0]}/{file_sr[1]}; "
                f"using the namelist values {sr_x}/{sr_y} instead."
            )
    elif file_sr[0] is not None:
        sr_x, sr_y = file_sr
        sr_source = f"{basenames[0]} global attributes"
    else:
        parser.error(
            f"Fire subgrid ratios not found: '{basenames[0]}' has no sr_x/sr_y global "
            f"attributes and no namelist with subgrid_ratio_x/y was found at "
            f"'{args.namelist}'. Supply --namelist."
        )
    print(f"  subgrid_ratio_x = {sr_x},  subgrid_ratio_y = {sr_y}  (from {sr_source})")

    # ── Build WRF domain geometry ─────────────────────────────────────────────
    print(f"Reading domain geometry from {basenames[0]} ...")
    domain = read_domain_from_file(files[0], sr_x, sr_y, namelist_params=nml_params)
    print(
        f"  Atmospheric grid : {domain.nx} × {domain.ny} mass pts  "
        f"dx={domain.dx:.1f} m  dy={domain.dy:.1f} m"
    )

    fire_grid = build_fire_grid(domain)
    print(
        f"  Fire grid        : {fire_grid.nx_fire} × {fire_grid.ny_fire}  "
        f"({fire_grid.dx:.1f} m × {fire_grid.dy:.1f} m cells)"
    )

    # ── Load fuel table ───────────────────────────────────────────────────────
    fuel_table = get_fuel_table(args.fuel_table)
    print(f"Fuel table: {fuel_table.name}  —  {fuel_table.description}")

    # ── Download any missing source rasters ───────────────────────────────────
    if args.fuel is None or args.zsf is None:
        # Imported lazily so environments without `requests` can still run
        # with locally supplied rasters.
        from .download import (
            fire_grid_bbox_wgs84, bbox_tag, resolve_landfire_layer,
            download_landfire, download_usgs_dem,
        )
        bbox = fire_grid_bbox_wgs84(fire_grid)
        tag = bbox_tag(bbox)
        os.makedirs(args.download_dir, exist_ok=True)
        print(
            f"Download area (WGS84): W={bbox[0]:.4f}  S={bbox[1]:.4f}  "
            f"E={bbox[2]:.4f}  N={bbox[3]:.4f}"
        )

        if args.fuel is None:
            product = _FUEL_TABLE_PRODUCT.get(fuel_table.name)
            if product is None:
                parser.error(
                    "--fuel is required when using a custom fuel table "
                    "(cannot infer which LANDFIRE product to download)."
                )
            print(f"No fuel raster given; downloading {product} from LANDFIRE ...")
            layer = resolve_landfire_layer(product, args.landfire_version)
            args.fuel = download_landfire(
                layer, bbox, os.path.join(args.download_dir, f"{layer}_{tag}.tif"),
                args.email,
            )

        if args.zsf is None:
            if args.zsf_source == "landfire":
                print("No terrain DEM given; downloading elevation from LANDFIRE ...")
                layer = resolve_landfire_layer("Elev")
                args.zsf = download_landfire(
                    layer, bbox, os.path.join(args.download_dir, f"{layer}_{tag}.tif"),
                    args.email,
                )
            else:
                print("No terrain DEM given; downloading 1/3 arc-second DEM from the USGS National Map ...")
                args.zsf = download_usgs_dem(
                    bbox, args.download_dir,
                    os.path.join(args.download_dir, f"USGS_3DEP_13as_{tag}.tif"),
                )

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
    zsf = reproject_dem(args.zsf, fire_grid, fill_value=args.zsf_fill)
    print(
        f"  ZSF shape {zsf.shape}  "
        f"range [{zsf.min():.1f}, {zsf.max():.1f}] m"
    )

    # ── Write to WPS files ─────────────────────────────────────────────────
    skipped = 0
    for file_path in files:
        label = os.path.basename(file_path)
        existing = check_existing_fire_vars(file_path)
        overwrite = args.overwrite

        if existing and not overwrite:
            overwrite = prompt_overwrite(file_path, existing)
            if not overwrite:
                print(f"  Skipped {label}.")
                skipped += 1
                continue

        print(f"  Writing {label} ... ", end="", flush=True)
        write_fire_vars(
            file_path, nfuel, zsf, sr_x, sr_y,
            nfuel_description=f"Fuel category for fire model ({fuel_table.description})",
            zsf_description=f"Topography height; source: {os.path.basename(args.zsf)}",
            overwrite=overwrite,
        )
        print("done.")

    written = len(files) - skipped
    print(f"\nFinished: {written} file(s) updated, {skipped} skipped.")
    if written == 0:
        sys.exit(1)
