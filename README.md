# fire_preprocess

A standalone Python tool that adds fire-specific input fields (`NFUEL_CAT` and `ZSF`) directly to
WPS output files (`geo_em` or `met_em`) for use with the Community Fire Behavior Model
(https://github.com/NCAR/fire_behavior), bypassing the traditional workflow that requires
converting data to WPS geogrid binary format and editing `GEOGRID.TBL`.

---

## 1. Environment setup

### conda (recommended)

```bash
conda env create -f environment.yaml
conda activate fire_preprocess
```

### pip

```bash
pip install -r requirements.txt
```

---

## 2. Input data

Two source datasets are needed: LANDFIRE fuel categories (NFUEL_CAT) and a
high-resolution terrain DEM (ZSF). By default both are **downloaded
automatically** for the exact WRF domain; supplying local GeoTIFF files with
`--fuel` / `--zsf` is still supported.

### Automatic download (default)

If `--fuel` or `--zsf` is not given, the tool computes the domain's bounding
box (plus a 2 km buffer) and fetches the data itself:

- **NFUEL_CAT** — requested from the [LANDFIRE Product Service
  (LFPS)](https://lfps.usgs.gov). The product matches `--fuel-table`
  (`fbfm13` → FBFM13, `fbfm40`/`fbfm40_to_anderson13` → FBFM40), using the
  newest full-coverage LANDFIRE version (pin one with `--landfire-version`,
  e.g. `LF2023`). *LFPS requires an email address* (`--email`), used by
  LANDFIRE only for usage reporting.
- **ZSF** — from the USGS National Map (3DEP **1/3 arc-second**, ~10 m) by
  default. The required 1°×1° tiles (~350 MB each) are downloaded and
  merged/clipped to the domain. Alternatively `--zsf-source landfire` fetches
  LANDFIRE's 30 m elevation through LFPS instead — a much smaller download at
  the cost of resolution.

Everything lands in `--download-dir` (default `./downloads`) and is cached:
re-running the tool for the same domain reuses the existing files, and DEM
tiles are shared between overlapping domains.

```bash
python fire_preprocess.py --wps-files geo_em.d03.nc --email you@example.org
```

### Manual download

Both datasets are also available interactively as GeoTIFF for any region of
the contiguous US.

**Fuel categories** — from the [LANDFIRE data viewer](https://landfire.gov/viewer/):

1. Draw your area of interest on the map.
2. Under *Fire Behavior Fuel Models*, select either:
   - **FBFM13** – Anderson 13-category model (default)
   - **FBFM40** – Scott & Burgan 40-category model
3. Choose **GeoTIFF** as the output format and download.
4. If the download covers multiple tiles, merge them before use:
   ```bash
   rio merge LF2025_FBFM13_*.tif --output fuel.tif
   ```

**High-resolution terrain** — from the [USGS National Map / 3D Elevation
Program (3DEP)](https://apps.nationalmap.gov/downloader/):

1. Under *Elevation Products (3DEP)*, select **1/3 Arc-Second DEM** (~10 m).
   1 Arc-Second (~30 m) is also available if coarser resolution is acceptable.
2. Select your area of interest and download.
3. Merge tiles if needed:
   ```bash
   rio merge USGS_13_*.tif --output dem.tif
   ```

---

## 3. Running the tool

### Command-line usage

Minimal — settings are read from the WPS file itself and both rasters are
downloaded automatically:

```bash
python fire_preprocess.py --wps-files geo_em.d02.nc --email you@example.org
```

With local input files:

```bash
python fire_preprocess.py \
    --wps-files geo_em.d02.nc \
    --fuel      fuel.tif \
    --zsf       dem.tif \
    --namelist  namelist.wps \
    --domain    2
```

All arguments can also be supplied via a YAML config file (see below).

### Command-line arguments

| Argument | Default | Description |
|---|---|---|
| `--wps-files` | — | WPS output file (`geo_em`/`met_em`) or glob pattern (e.g. `'met_em.d02.*.nc'`) |
| `--fuel` | *download* | LANDFIRE fuel-category GeoTIFF (NFUEL_CAT source); downloaded automatically if omitted |
| `--zsf` | *download* | High-resolution terrain DEM GeoTIFF (ZSF source); downloaded automatically if omitted |
| `--zsf-source` | `nationalmap` | Source for automatic ZSF download: `nationalmap` (USGS 3DEP 1/3 arc-sec, ~10 m) or `landfire` (30 m, much smaller download) |
| `--email` | — | Email address; required by the LANDFIRE Product Service when downloading |
| `--landfire-version` | newest full-coverage | Pin the LANDFIRE version of downloaded fuel data (e.g. `LF2023`) |
| `--download-dir` | `downloads` | Cache directory for downloaded rasters |
| `--namelist` | `namelist.wps` | Path to `namelist.wps`. Optional: if absent, `subgrid_ratio_x/y` are read from the WPS file's `sr_x`/`sr_y` global attributes (a namelist value overrides the file) |
| `--domain` | `1` | Domain number, used to read the correct `subgrid_ratio_x/y` from the namelist |
| `--fuel-table` | `fbfm13` | Fuel remapping table (see below) |
| `--overwrite` | `false` | Overwrite existing fire fields without prompting |
| `--config` | `config.yaml` | YAML config file (loaded automatically if present) |

### Config file

Any argument can be set in a YAML config file. CLI flags override config values.

```yaml
wps_files:  'met_em.d02.2024-09-08_*.nc'
zsf:        /path/to/dem.tif      # omit to download automatically
fuel:       /path/to/fuel.tif     # omit to download automatically
namelist:   namelist.wps
fuel_table: fbfm13
domain:     2
overwrite:  false
zsf_source: nationalmap
email:      you@example.org       # required for LANDFIRE downloads
download_dir: downloads
```

Run with a config file:

```bash
python fire_preprocess.py --config config.yaml
```

### Fuel tables

| Name | Description |
|---|---|
| `fbfm13` | Anderson 13-category model — LANDFIRE codes 1–13 passed through directly (default) |
| `fbfm40` | Scott & Burgan 40-category model — LANDFIRE 3-digit codes (101–204) passed through unchanged; CFBM converts them to Anderson 13 internally via `Crosswalk_from_scottburgan_to_anderson` |
| `fbfm40_to_anderson13` | Scott & Burgan 40 pre-converted to Anderson 13 using the exact crosswalk from CFBM's `fuel_mod.F90` |

A custom remapping can be supplied as a two-column CSV file:

```
source,target
1,1
2,2
101,1
91,14
```

```bash
python fire_preprocess.py --fuel-table my_remap.csv ...
```

---

## Background

The standard CFBM workflow requires:

1. Downloading LANDFIRE and USGS terrain data in their native formats
2. Converting both datasets to WPS geogrid binary format (a technically
   involved process with no widely-available open-source tooling)
3. Manually adding `NFUEL_CAT` and `ZSF` entries with `subgrid=yes` to
   `GEOGRID.TBL`
4. Re-running `geogrid.exe` to embed the fire fields

`fire_preprocess` replaces steps 2–4 entirely. It reads GeoTIFF directly,
reprojects to the WRF fire subgrid using the projection parameters and
`subgrid_ratio_x/y` values from `namelist.wps`, and writes `NFUEL_CAT` and
`ZSF` into the existing WPS netCDF files. The rest of the workflow
(`real.exe` → WRF) is unchanged.
