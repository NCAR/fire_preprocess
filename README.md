# fire_preprocess

A standalone Python tool that adds fire-specific input fields (`NFUEL_CAT`, `ZSF`, `DZDXF`,
`DZDYF`) directly to WPS output files (`geo_em` or `met_em`) for use with the Community Fire
Behavior Model (https://github.com/NCAR/fire_behavior), bypassing the traditional workflow
that requires converting data to WPS geogrid binary format and editing `GEOGRID.TBL`.

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

If `--fuel` or `--zsf` is not given, the tool computes the fire grid's
bounding box (plus a 2 km buffer, rounded outward to 0.05° so nearby domains
share downloads) and fetches the data itself:

- **NFUEL_CAT** — requested from the [LANDFIRE Product Service
  (LFPS)](https://lfps.usgs.gov). The product matches `--fuel-table`
  (`fbfm13` → FBFM13, `fbfm40`/`fbfm40_to_anderson13` → FBFM40), using the
  newest full-coverage LANDFIRE version (pin one with `--landfire-version`,
  e.g. `LF2023`). *LFPS requires an email address* (`--email`), used by
  LANDFIRE only for usage reporting.
- **ZSF** — from the USGS National Map (3DEP **1/3 arc-second**, ~10 m) by
  default. Only the part of each 1°×1° tile the domain needs is read
  (straight from the USGS server), using the newest publication of each
  tile, and merged/clipped into one GeoTIFF. A tile missing from 3DEP is an
  error rather than a gap; cells inside a tile without data are open water
  and are set to 0 m. Alternatively `--zsf-source landfire` fetches
  LANDFIRE's 30 m elevation through LFPS instead — a much smaller download at
  the cost of resolution.

Everything lands in `--download-dir` (default `./downloads`), with a `.json`
beside each file recording where it came from, and is cached: re-running the
tool for the same area reuses the existing files. Both web services return
transient errors now and then; requests are retried with back-off.

By default a raster that covers only part of the fire grid is fine: cells
outside it are filled as described in [Clipped source
rasters](#clipped-source-rasters). `--strict-coverage` requires both rasters
to cover the whole fire grid instead, and stops without writing anything if
a cell lies outside either one's extent; use it when a shortfall can only
mean the wrong file or area, as with automatic downloads. Nodata cells
*inside* a raster, such as ocean, are always filled, so coastal domains
aren't rejected.

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
| `--wps-files` | — | WPS output file (`geo_em`/`met_em`) or glob pattern (e.g. `'met_em.d02.*.nc'`); with `--copy-from`, any WPS or WRF netCDF file such as `wrfinput_d02` |
| `--fuel` | *download* | LANDFIRE fuel-category GeoTIFF (NFUEL_CAT source); downloaded automatically if omitted |
| `--zsf` | *download* | High-resolution terrain DEM GeoTIFF (ZSF source); downloaded automatically if omitted |
| `--zsf-source` | `nationalmap` | Source for automatic ZSF download: `nationalmap` (USGS 3DEP 1/3 arc-sec, ~10 m) or `landfire` (30 m, much smaller download) |
| `--email` | `$LANDFIRE_EMAIL` | Email address; required by the LANDFIRE Product Service when downloading |
| `--landfire-version` | newest full-coverage | Pin the LANDFIRE version of downloaded fuel data (e.g. `LF2023`) |
| `--download-dir` | `downloads` | Cache directory for downloaded rasters |
| `--strict-coverage` | `false` | Require the rasters to cover the whole fire grid; stop instead of filling cells outside them. Nodata inside a raster (e.g. ocean) is still filled |
| `--namelist` | `namelist.wps` | Path to `namelist.wps`. Optional: if absent, `subgrid_ratio_x/y` are read from the WPS file's `sr_x`/`sr_y` global attributes (a namelist value overrides the file) |
| `--domain` | `1` | Domain number, used to read the correct `subgrid_ratio_x/y` from the namelist |
| `--fuel-table` | `fbfm13` | Fuel remapping table (see below) |
| `--overwrite` | `false` | Overwrite existing fire fields without prompting |
| `--config` | `config.yaml` | YAML config file (loaded automatically if present) |
| `--copy-from` | — | Copy the fields from this netCDF file instead of building them from GeoTIFFs (see below) |
| `--vars` | all four | With `--copy-from`: comma-separated fields to copy |
| `--perimeter` | — | Write `lfn_init` (observed-perimeter ignition) from this GeoJSON instead (see below) |

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

### Copying fields from another file (`--copy-from`)

Some files describe a fire grid but come without its fields. The main case
is WRF's `ndown.exe`: the `wrfinput_d02` it writes leaves out `NFUEL_CAT`,
`ZSF`, `DZDXF` and `DZDYF`, though its fine-grid template (`wrfndi_d02`) has
them, so a fire run started from it has no fuel. `--copy-from` copies the
fields from one netCDF file into another as they are, with no reprojection:

```bash
python fire_preprocess.py --copy-from wrfndi_d02 --wps-files wrfinput_d02
```

- Source and target can be any WPS or WRF netCDF file (`geo_em`, `met_em`,
  `wrfinput`, `wrfndi`, ...). `--wps-files` may be a glob.
- They must be on the same grid. The tool checks the fire-subgrid size,
  `DX`/`DY` and the atmospheric-grid latitudes and longitudes, and stops
  without writing anything if they differ.
- A field the target already has keeps the target's own attributes (so a
  WRF file keeps WRF's metadata); only its values are replaced. A field it
  lacks is created with the source's attributes.
- Existing values are replaced without prompting: `--copy-from` is itself
  the request.
- `--vars` limits the copy, e.g. `--vars NFUEL_CAT` to swap in another
  file's fuels and keep the target's terrain.
- `--fuel`, `--zsf`, `--namelist`, `--domain` and `--fuel-table` don't apply.
  `copy_from` and `vars` can also be given in the config file.

### Starting the fire from an observed perimeter (`--perimeter`)

With `fire_is_real_perim = .true.`, CFBM starts the fire from a level-set
field instead of a point or line ignition: at the ignition start time
(`fire_ignition_start_time1`) it copies `lfn_init` into its level-set
function, where negative is burnt and positive is not. `--perimeter` makes
`lfn_init` from a GeoJSON perimeter and writes it into the fire domain's
`geo_em`:

```bash
python fire_preprocess.py --perimeter perimeter.geojson \
    --wps-files geo_em.d03.nc --namelist namelist.wps --domain 3
```

- The GeoJSON is a FeatureCollection, Feature, Polygon or MultiPolygon in
  longitude/latitude (WGS84), as perimeter services such as NIFC's publish.
  Holes are kept: an unburnt island stays unburnt.
- Each fire-grid cell gets its signed distance to the perimeter in meters,
  negative inside, accurate to about half a fire cell. The tool prints the
  burnt area and the value range.
- It stops if the perimeter extends beyond the fire domain (a cut-off
  perimeter would start the wrong fire), or covers no cell or every cell.
- `lfn_init` is written as CFBM reads it: a 2-D float on the fire subgrid
  (`south_north_subgrid` x `west_east_subgrid`, no `Time` dimension).
  Rerunning replaces it.
- Needs `scipy` (in `environment.yaml`); the other modes don't.
- **CFBM reads `lfn_init` only when it starts from `geo_em` (standalone).**
  Coupled to WRF, it stops with "Not ready to initialize from fire perimeter
  inside WRF" (`state/state_mod.F90`).

### Clipped source rasters

The fuel and high-resolution DEM GeoTIFFs may cover only the intended fire
area. Outside their joint valid coverage, `NFUEL_CAT` is set to the selected
fuel table's no-fuel category. `ZSF` remains finite over the full fire array by
bilinearly interpolating the atmospheric `HGT_M` field to the fire grid, then
overlaying the high-resolution DEM where both rasters are valid.

`DZDXF` and `DZDYF` are calculated from the merged `ZSF` using centered
differences in the interior, one-sided differences at array edges, and WRF
projection map factors. Both gradients are set to zero wherever their
two-dimensional finite-difference stencil crosses the clipped-data boundary.
This prevents a terrain discontinuity at the boundary from entering the fire
spread calculation.

### Terrain gradients

`DZDXF` and `DZDYF` are always written alongside `ZSF`.

The stencil matches geogrid's `calc_dfdx`/`calc_dfdy` (WPS
`geogrid/src/process_tile_module.f90`): a centered difference over two fire cells in the
interior, one-sided at the domain edges, and zero where a stencil crosses the edge of
clipped source data (see above). The map scale factor is applied, so the gradients
remain correct on domains large enough for it to matter.
Be aware that the sense of the correction is the **opposite** of geogrid's: WRF measures
grid spacing in projection space and takes the true distance between grid points to be
`dx/MAPFAC` — `dyn_em/module_diffusion_em.F` forms its physical mixing length as
`sqrt(dx/msftx * dy/msfty)` — so a physical gradient must *multiply* by the map factor,
whereas `calc_dfdx` divides by it. The factor is evaluated at fire-grid cell centers with
`pyproj`, which reproduces WPS's own analytic formula to 6×10⁻¹².

Note that geogrid applies `smooth_option = smth-desmth_special, smooth_passes = 1` to `ZSF`
before differentiating it. This tool does not smooth, so in steep terrain the gradients are
somewhat noisier than a geogrid-produced file would be.

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
subgrid ratios from the WPS file itself (or `namelist.wps`), and writes the fire fields
into the existing WPS netCDF files. The rest of the workflow
(`real.exe` → WRF) is unchanged.
