"""Download source rasters for NFUEL_CAT and ZSF from public web services.

Fuel categories (NFUEL_CAT) come from the LANDFIRE Product Service (LFPS):
  https://lfps.usgs.gov  — REST API; asynchronous jobs return a zipped GeoTIFF
  clipped to the requested bounding box. LFPS requires an email address with
  every request (used by LANDFIRE for usage reporting only).

Terrain (ZSF) comes from either:
  - USGS National Map / 3DEP via the TNM Access API (default; 1/3 arc-second,
    ~10 m): https://tnmaccess.nationalmap.gov/api/v1/products
    Only the part of each 1°x1° tile the domain needs is read (over HTTP,
    with GDAL's /vsicurl/), then merged and clipped into one GeoTIFF.
  - LANDFIRE elevation (LF2020_Elev, 30 m) through the same LFPS API — much
    smaller download, but coarser than 3DEP.

All downloads land in a cache directory; a file that already exists there
(same layer + bounding box) is reused instead of re-downloaded. The download
area is the fire grid plus a buffer, rounded outward to 0.05°, so nearby
runs over the same domain share one download. Each download gets a .json
file beside it recording where it came from.
"""
import json
import math
import os
import re
import time
import warnings
import zipfile

import numpy as np
import requests
import rasterio
from rasterio.merge import merge as rio_merge
from pyproj import CRS, Transformer

from .fire_grid import FireGrid
from .wrf_domain import WRF_SPHERE_RADIUS

# Download areas are rounded outward to this many degrees, so the cache is
# shared by runs whose domains differ slightly.
BBOX_STEP = 0.05

LFPS_API = "https://lfps.usgs.gov/api"
TNM_API = "https://tnmaccess.nationalmap.gov/api/v1/products"
TNM_DEM_DATASET = "National Elevation Dataset (NED) 1/3 arc-second"

# Used only if the live LFPS product listing cannot be queried.
FALLBACK_LAYERS = {
    "FBFM13": "LF2024_FBFM13",
    "FBFM40": "LF2024_FBFM40",
    "Elev": "LF2020_Elev",
}

_CHUNK = 1 << 20  # 1 MiB


# ── Bounding box ──────────────────────────────────────────────────────────────

def fire_grid_bbox_wgs84(fire_grid: FireGrid, buffer_m: float = 2000.0):
    """Return (west, south, east, north) lat/lon bounds covering the fire grid.

    Samples points along the grid perimeter (projected edges are curved in
    lat/lon) and pads by *buffer_m* so edge pixels are fully covered by the
    downloaded data. WRF's spherical lat/lon values are used directly as
    WGS84, following the standard WRF convention of ignoring the
    sphere-vs-ellipsoid datum shift.
    """
    t = fire_grid.transform
    x0, y_north = t.c, t.f
    x1 = x0 + t.a * fire_grid.nx_fire
    y_south = y_north + t.e * fire_grid.ny_fire

    n = 50
    xs = np.linspace(x0, x1, n)
    ys = np.linspace(y_south, y_north, n)
    edge_x = np.concatenate([xs, xs, np.full(n, x0), np.full(n, x1)])
    edge_y = np.concatenate([np.full(n, y_south), np.full(n, y_north), ys, ys])

    geo = CRS.from_proj4(
        f"+proj=longlat +a={WRF_SPHERE_RADIUS} +b={WRF_SPHERE_RADIUS} +no_defs"
    )
    lon, lat = Transformer.from_crs(fire_grid.crs, geo, always_xy=True).transform(edge_x, edge_y)

    blat = buffer_m / 111320.0
    blon = buffer_m / (111320.0 * math.cos(math.radians(float(np.abs(lat).max()))))
    return snap_bbox((
        float(lon.min()) - blon,
        float(lat.min()) - blat,
        float(lon.max()) + blon,
        float(lat.max()) + blat,
    ))


def snap_bbox(bbox, step: float = BBOX_STEP):
    """Round (west, south, east, north) outward to multiples of *step* degrees."""
    west, south, east, north = bbox
    down = lambda v: round(math.floor(v / step) * step, 6)
    up = lambda v: round(math.ceil(v / step) * step, 6)
    return (down(west), down(south), up(east), up(north))


def write_provenance(path: str, info: dict) -> None:
    """Record where a downloaded raster came from, in <path minus .tif>.json."""
    with open(os.path.splitext(path)[0] + ".json", "w") as fh:
        json.dump(info, fh, indent=2)
        fh.write("\n")


def bbox_tag(bbox) -> str:
    """Filename-friendly tag identifying a bounding box (used for cache names)."""
    return "_".join(f"{v:.2f}" for v in bbox)


def _get_json(url: str, params: dict = None, timeout: int = 60, retries: int = 4):
    """GET a JSON endpoint, retrying transient failures (5xx, timeouts).

    Both LFPS and the TNM Access API intermittently return gateway errors;
    a few retries with increasing back-off rides those out.
    """
    delay = 5
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code >= 500:
                raise requests.HTTPError(f"{r.status_code} for {r.url}", response=r)
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None and status < 500:
                raise  # 4xx: our request is wrong; retrying won't help
            if attempt == retries - 1:
                raise
            print(f"    Transient error from {url} ({exc}); retrying in {delay} s ...")
            time.sleep(delay)
            delay *= 2


def _stream_download(url: str, dest: str, label: str = None, size: int = None):
    """Download *url* to *dest*, atomically via a .part file."""
    label = label or os.path.basename(dest)
    size_txt = f" ({size / 1e6:.0f} MB)" if size else ""
    print(f"  Downloading {label}{size_txt} ...", flush=True)
    tmp = dest + ".part"
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(_CHUNK):
                fh.write(chunk)
    os.replace(tmp, dest)


# ── LANDFIRE Product Service ──────────────────────────────────────────────────

def resolve_landfire_layer(product: str, version: str = None) -> str:
    """Return the LFPS layer name (e.g. 'LF2024_FBFM13') for a product acronym.

    Queries the live LFPS product listing. *version* (e.g. 'LF2023') pins a
    specific LANDFIRE version; otherwise the newest version with full ('All')
    geographic coverage is preferred, because the newest release sometimes
    covers only part of CONUS (e.g. LF2025 covers only SW/NW GeoAreas).
    """
    try:
        products = _get_json(f"{LFPS_API}/products", timeout=30)["products"]
    except Exception as exc:
        layer = FALLBACK_LAYERS[product]
        warnings.warn(f"Could not query the LFPS product list ({exc}); falling back to '{layer}'.")
        return layer

    # Match on theme too: excludes 'Seasonal Fuels' variants like LF2025_FBFM40_SP26.
    cands = [
        p for p in products
        if p.get("acronym") == product and p.get("theme") in ("Fuels", "Topographic")
    ]
    if not cands:
        raise ValueError(f"No LFPS product found with acronym '{product}'.")

    if version:
        for p in cands:
            if p["version"].lower() == version.lower():
                return p["layerName"]
        avail = sorted({p["version"] for p in cands})
        raise ValueError(
            f"LFPS has no {product} product for version '{version}'. "
            f"Available versions: {', '.join(avail)}"
        )

    full_coverage = [p for p in cands if p.get("geoAreas") == "All"]
    best = max(full_coverage or cands, key=lambda p: p["version"])
    return best["layerName"]


def download_landfire(layer: str, bbox, out_path: str, email: str,
                      poll_seconds: int = 10, timeout_seconds: int = 1800) -> str:
    """Fetch *layer* clipped to *bbox* via an asynchronous LFPS job.

    Returns *out_path* (reused as-is if it already exists).
    """
    if os.path.isfile(out_path):
        print(f"  Using cached download: {out_path}")
        return out_path
    if not email:
        raise ValueError(
            "LANDFIRE downloads require an email address (LFPS 'Email' parameter). "
            "Supply one with --email or the 'email' config key."
        )

    west, south, east, north = bbox
    params = {
        "Email": email,
        "Layer_List": layer,
        "Area_of_Interest": f"{west} {south} {east} {north}",
    }
    job = _get_json(f"{LFPS_API}/job/submit", params=params)
    job_id = job.get("jobId")
    if not job_id:
        raise RuntimeError(f"LFPS job submission failed: {job}")
    print(f"  LFPS job submitted: {job_id}  (layer {layer})")

    deadline = time.time() + timeout_seconds
    while True:
        status_json = _get_json(f"{LFPS_API}/job/status", params={"JobId": job_id})
        status = status_json.get("status", "")
        if status == "Succeeded":
            break
        if status in ("Failed", "Canceled"):
            msgs = status_json.get("messages", [])
            raise RuntimeError(f"LFPS job {job_id} {status.lower()}: {msgs}")
        if time.time() > deadline:
            raise TimeoutError(
                f"LFPS job {job_id} did not finish within {timeout_seconds} s "
                f"(last status: {status})."
            )
        pos = status_json.get("queuePosition")
        queue_txt = f", queue position {pos}" if pos not in (None, -1) else ""
        print(f"    LFPS job status: {status}{queue_txt} — retrying in {poll_seconds} s")
        time.sleep(poll_seconds)

    # LFPS names the result in outputFile; fall back to any .zip URL in the reply.
    url = status_json.get("outputFile")
    if not url:
        m = re.search(r'https?://[^"\s\\]+?\.zip', json.dumps(status_json))
        url = m.group(0) if m else None
    if not url:
        raise RuntimeError(
            f"LFPS job {job_id} succeeded but no download URL was found "
            f"in the status response: {status_json}"
        )

    zip_path = out_path + ".zip"
    _stream_download(url, zip_path, label=f"LFPS bundle {job_id}.zip")
    with zipfile.ZipFile(zip_path) as zf:
        tifs = [n for n in zf.namelist() if n.lower().endswith(".tif")]
        if not tifs:
            raise RuntimeError(f"No GeoTIFF found in the LFPS bundle {zip_path}")
        tmp = out_path + ".part"        # no partial file under the cached name
        with zf.open(tifs[0]) as src, open(tmp, "wb") as dst:
            while True:
                chunk = src.read(_CHUNK)
                if not chunk:
                    break
                dst.write(chunk)
        os.replace(tmp, out_path)
    os.remove(zip_path)
    write_provenance(out_path, {"source": "LANDFIRE Product Service", "layer": layer,
                                "bbox": list(bbox), "job": job_id, "url": url})
    print(f"  Saved {out_path}")
    return out_path


# ── USGS National Map (3DEP) ──────────────────────────────────────────────────

def _tnm_query(bbox, dataset: str) -> list:
    """Return all TNM product items for *dataset* intersecting *bbox*."""
    west, south, east, north = bbox
    items, offset = [], 0
    while True:
        params = {
            "datasets": dataset,
            "bbox": f"{west},{south},{east},{north}",
            "prodFormats": "GeoTIFF",
            "outputFormat": "JSON",
            "max": 100,
            "offset": offset,
        }
        payload = _get_json(TNM_API, params=params, timeout=120)
        batch = payload.get("items", [])
        items.extend(batch)
        offset += len(batch)
        if not batch or offset >= int(payload.get("total", 0)):
            return items


def _latest_per_tile(items: list) -> list:
    """Keep only the most recent product per 1°x1° tile (drops superseded versions)."""
    tiles = {}
    for it in items:
        url = it.get("downloadURL") or ""
        if not url.lower().endswith(".tif"):
            continue
        m = re.search(r"[ns]\d{2,3}[ew]\d{3}", url)
        key = m.group(0) if m else url
        prev = tiles.get(key)
        if prev is None or (it.get("publicationDate") or "") > (prev.get("publicationDate") or ""):
            tiles[key] = it
    return list(tiles.values())


def _required_tiles(bbox) -> set:
    """The 1°x1° 3DEP tile names (e.g. n36w084: 35-36°N, 84-83°W) a western-
    and northern-hemisphere bbox touches. Empty elsewhere: no check there."""
    west, south, east, north = bbox
    if west >= 0 or south < 0:
        return set()
    return {f"n{lat:02d}w{-lon:03d}"
            for lat in range(math.floor(south) + 1, math.ceil(north) + 1)
            for lon in range(math.floor(west), math.ceil(east))}


def download_usgs_dem(bbox, download_dir: str, out_path: str,
                      dataset: str = TNM_DEM_DATASET) -> str:
    """The 3DEP DEM over *bbox*, as one clipped GeoTIFF at *out_path*.

    Reads only the part of each covering tile that's needed, straight from
    the USGS server (GDAL /vsicurl/), rather than downloading whole tiles
    (~350 MB each). Uses the newest publication of each tile. A tile missing
    from 3DEP is an error -- the gap would otherwise reach ZSF as a fill
    value. Cells inside a tile without data are open water and are set to
    0 m (sea level), as geogrid does, so they are not mistaken for missing
    coverage. Returns *out_path* (reused as-is if it already exists).
    *download_dir* is unused and kept for compatibility.
    """
    if os.path.isfile(out_path):
        print(f"  Using cached download: {out_path}")
        return out_path

    print(f"  Querying the USGS National Map: {dataset}")
    tiles = _latest_per_tile(_tnm_query(bbox, dataset))
    if not tiles:
        raise RuntimeError(
            f"The USGS National Map returned no '{dataset}' products for bbox {bbox}. "
            "Check that the domain is inside 3DEP coverage, or use --zsf-source landfire."
        )
    have = set()
    for it in tiles:
        m = re.search(r"[ns]\d{2,3}[ew]\d{3}", it["downloadURL"])
        if m:
            have.add(m.group(0))
    missing = sorted(_required_tiles(bbox) - have)
    if missing:
        raise RuntimeError(f"3DEP has no tile(s) {', '.join(missing)} for bbox {bbox}; "
                           "use --zsf-source landfire or supply --zsf")

    urls = sorted(it["downloadURL"] for it in tiles)
    print(f"  Reading {len(urls)} DEM tile(s), clipped to the domain")
    sources = [rasterio.open(f"/vsicurl/{u}") for u in urls]
    try:
        nodata = sources[0].nodata
        data, transform = rio_merge(sources, bounds=bbox, nodata=nodata)
        profile = sources[0].profile.copy()
    finally:
        for s in sources:
            s.close()
    band = data[0]
    water = (band == nodata) if nodata is not None else np.zeros(band.shape, bool)
    band[water] = 0.0
    profile.update(driver="GTiff", height=band.shape[0], width=band.shape[1], count=1,
                   transform=transform, compress="deflate", tiled=True,
                   blockxsize=256, blockysize=256, nodata=None)
    tmp = out_path + ".part"
    with rasterio.open(tmp, "w", **profile) as dst:
        dst.write(band, 1)
    os.replace(tmp, out_path)
    write_provenance(out_path, {"source": "USGS 3DEP 1/3 arc-second", "bbox": list(bbox),
                                "tiles": urls, "water_cells_set_to_0": int(water.sum())})
    print(f"  Saved {out_path}")
    return out_path
