"""Command-line interface for fire_preprocess."""
import argparse
import os
import sys

from .namelist import get_fire_subgrid_ratios, get_domain_params
from .wrf_domain import read_domain_from_met_em
from .fire_grid import build_fire_grid
from .raster import reproject_fuel, reproject_dem
from .fuel_tables import get_fuel_table, list_fuel_tables
from .met_em_io import find_met_em_files, check_existing_fire_vars, prompt_overwrite, write_fire_vars


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fire_preprocess",
        description=(
            "Add WRF-FIRE fields (NFUEL_CAT, ZSF) directly to met_em netCDF files,\n"
            "bypassing GEOGRID.TBL editing and geogrid binary format conversion."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            f"Built-in fuel tables: {', '.join(list_fuel_tables())}\n\n"
            "Example:\n"
            "  fire_preprocess \\\n"
            "      --met-em /path/to/WPS/ \\\n"
            "      --fuel   LANDFIRE_FBFM13.tif \\\n"
            "      --dem    usgs_1_3arcsec.tif \\\n"
            "      --namelist namelist.wps\n"
        ),
    )
    parser.add_argument(
        "--met-em", required=True, metavar="PATH",
        help=(
            "Path to a met_em file, a directory containing met_em files, "
            "or a glob pattern (e.g. 'WPS/met_em.d01.*.nc')"
        ),
    )
    parser.add_argument(
        "--fuel", required=True, metavar="GEOTIFF",
        help="LANDFIRE fuel-category GeoTIFF used as the NFUEL_CAT source",
    )
    parser.add_argument(
        "--dem", required=True, metavar="GEOTIFF",
        help="High-resolution terrain DEM GeoTIFF used as the ZSF source (≥1/3 arc-sec recommended)",
    )
    parser.add_argument(
        "--namelist", required=True, metavar="FILE",
        help="Path to namelist.wps (provides subgrid_ratio_x/y and projection parameters)",
    )
    parser.add_argument(
        "--fuel-table", default="fbfm13", metavar="NAME|PATH",
        help=(
            f"Fuel remapping table: built-in name or path to a CSV file. "
            f"Default: fbfm13. "
            f"Available: {', '.join(list_fuel_tables())}"
        ),
    )
    parser.add_argument(
        "--domain", type=int, default=1, metavar="N",
        help="Domain number used when searching a directory for met_em files. Default: 1",
    )
    parser.add_argument(
        "-y", "--yes", action="store_true",
        help="Overwrite existing NFUEL_CAT/ZSF variables without prompting",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

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
