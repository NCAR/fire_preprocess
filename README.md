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

## 2. Retrieving input data

Two datasets are required. Both are available as GeoTIFF and can be downloaded
for any region of the contiguous US.

### Fuel categories (NFUEL_CAT)

Download from the **LANDFIRE data viewer**:
<https://landfire.gov/viewer/>

1. Draw your area of interest on the map.
2. Under *Fire Behavior Fuel Models*, select either:
   - **FBFM13** – Anderson 13-category model (default)
   - **FBFM40** – Scott & Burgan 40-category model
3. Choose **GeoTIFF** as the output format and download.
4. If the download covers multiple tiles, merge them before use:
   ```bash
   rio merge LF2025_FBFM13_*.tif --output fuel.tif
   ```

### High-resolution terrain (ZSF)

Download from the **USGS National Map / 3D Elevation Program (3DEP)**:
<https://apps.nationalmap.gov/downloader/>

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
| `--fuel` | — | LANDFIRE fuel-category GeoTIFF (NFUEL_CAT source) |
| `--zsf` | — | High-resolution terrain DEM GeoTIFF (ZSF source) |
| `--namelist` | `namelist.wps` | Path to `namelist.wps` |
| `--domain` | `1` | Domain number, used to read the correct `subgrid_ratio_x/y` from the namelist |
| `--fuel-table` | `fbfm13` | Fuel remapping table (see below) |
| `--overwrite` | `false` | Overwrite existing fire fields without prompting |
| `--config` | `config.yaml` | YAML config file (loaded automatically if present) |

### Config file

Any argument can be set in a YAML config file. CLI flags override config values.

```yaml
wps_files:  'met_em.d02.2024-09-08_*.nc'
zsf:        /path/to/dem.tif
fuel:       /path/to/fuel.tif
namelist:   namelist.wps
fuel_table: fbfm13
domain:     2
overwrite:  false
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

### Terrain gradients

`DZDXF` and `DZDYF` are always written alongside `ZSF`.

The stencil matches geogrid's `calc_dfdx`/`calc_dfdy` (WPS
`geogrid/src/process_tile_module.f90`): a centred difference over two fire cells in the
interior, one-sided at the domain edges. The map scale factor is applied, so the gradients
remain correct on domains large enough for it to matter.
Be aware that the sense of the correction is the **opposite** of geogrid's: WRF measures
grid spacing in projection space and takes the true distance between grid points to be
`dx/MAPFAC` — `dyn_em/module_diffusion_em.F` forms its physical mixing length as
`sqrt(dx/msftx * dy/msfty)` — so a physical gradient must *multiply* by the map factor,
whereas `calc_dfdx` divides by it. The factor is evaluated at fire-grid cell centres with
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
`subgrid_ratio_x/y` values from `namelist.wps`, and writes the fire fields
into the existing WPS netCDF files. The rest of the workflow
(`real.exe` → WRF) is unchanged.
