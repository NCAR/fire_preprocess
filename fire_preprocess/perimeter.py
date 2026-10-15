"""Start the fire from an observed perimeter: the lfn_init field.

With `fire_is_real_perim = .true.`, CFBM starts the fire from a level-set
field instead of a point or line ignition: at the ignition start time it
copies `lfn_init` into its level-set function (lfn), where lfn < 0 is burnt
and lfn > 0 is not, so the fire front is lfn = 0. CFBM reads `lfn_init` from
geo_em as a 2-D float variable (south_north_subgrid x west_east_subgrid, no
Time dimension) on the fire grid.

This module turns a GeoJSON perimeter into that field: the polygon is
projected onto the fire grid and burned in, and each cell gets its signed
distance to the perimeter, in metres (negative inside). Distances are
measured between fire-cell centres, so they are good to about half a fire
cell -- the grid's own resolution.
"""
import json

import netCDF4 as nc
import numpy as np
from pyproj import Transformer
from rasterio.features import rasterize

from .fire_grid import FireGrid
from .wps_io import _DIM_SN, _DIM_WE, _ensure_dim

VAR = "lfn_init"
_WGS84 = {"urn:ogc:def:crs:OGC:1.3:CRS84", "urn:ogc:def:crs:OGC::CRS84",
          "EPSG:4326", "urn:ogc:def:crs:EPSG::4326"}


def read_perimeter(path: str) -> list:
    """The polygon geometries in a GeoJSON file (a FeatureCollection, a
    Feature, or a bare Polygon / MultiPolygon), in longitude/latitude."""
    with open(path) as fh:
        doc = json.load(fh)
    crs = (((doc.get("crs") or {}).get("properties") or {}).get("name"))
    if crs and crs not in _WGS84:
        raise ValueError(f"coordinates are in {crs}; GeoJSON perimeters must be "
                         f"longitude/latitude (WGS84)")
    if doc.get("type") == "FeatureCollection":
        geoms = [f.get("geometry") for f in doc.get("features", [])]
    elif doc.get("type") == "Feature":
        geoms = [doc.get("geometry")]
    else:
        geoms = [doc]
    polys = [g for g in geoms if g and g.get("type") in ("Polygon", "MultiPolygon")]
    if not polys:
        raise ValueError("no Polygon or MultiPolygon geometry found")
    return polys


def _project(geom: dict, to_grid) -> dict:
    """A Polygon / MultiPolygon with its rings projected to the grid's CRS."""
    def ring(r):
        x, y = to_grid.transform(*np.asarray(r, dtype=float)[:, :2].T)
        return np.column_stack([x, y]).tolist()
    if geom["type"] == "Polygon":
        return {"type": "Polygon", "coordinates": [ring(r) for r in geom["coordinates"]]}
    return {"type": "MultiPolygon",
            "coordinates": [[ring(r) for r in p] for p in geom["coordinates"]]}


def burnt_mask(polys: list, fire_grid: FireGrid) -> np.ndarray:
    """True where a fire-cell centre is inside the perimeter. Row 0 is the
    southernmost row, as in WPS/WRF files. Raises ValueError if the
    perimeter is not entirely inside the fire grid."""
    to_grid = Transformer.from_crs("EPSG:4326", fire_grid.crs, always_xy=True)
    projected = [_project(g, to_grid) for g in polys]

    x0, y_top = fire_grid.transform.c, fire_grid.transform.f
    x1 = x0 + fire_grid.nx_fire * fire_grid.dx
    y0 = y_top - fire_grid.ny_fire * fire_grid.dy
    xs, ys = [], []
    for g in projected:
        rings = g["coordinates"] if g["type"] == "Polygon" else [r for p in g["coordinates"] for r in p]
        for r in rings:
            a = np.asarray(r)
            xs.append(a[:, 0])
            ys.append(a[:, 1])
    xs, ys = np.concatenate(xs), np.concatenate(ys)
    if xs.min() < x0 or xs.max() > x1 or ys.min() < y0 or ys.max() > y_top:
        raise ValueError(
            "the perimeter extends beyond the fire domain: a perimeter cut off at "
            "the domain edge would start the wrong fire")

    mask = rasterize([(g, 1) for g in projected],
                     out_shape=(fire_grid.ny_fire, fire_grid.nx_fire),
                     transform=fire_grid.transform, fill=0, dtype="uint8")
    return np.flipud(mask.astype(bool))      # rasterio: row 0 = north


def signed_distance(mask: np.ndarray, dx: float, dy: float) -> np.ndarray:
    """Distance to the perimeter in metres, negative inside (burnt). The
    boundary lies between a burnt and an unburnt cell centre, so half a
    cell is taken off each side's centre-to-centre distance."""
    from scipy.ndimage import distance_transform_edt
    if not mask.any():
        raise ValueError("the perimeter covers no fire-grid cell centre")
    if mask.all():
        raise ValueError("the perimeter covers the whole fire domain")
    half = 0.5 * min(dx, dy)
    inside = distance_transform_edt(mask, sampling=(dy, dx))
    outside = distance_transform_edt(~mask, sampling=(dy, dx))
    return np.where(mask, -(inside - half), outside - half).astype(np.float32)


def write_lfn_init(path: str, lfn: np.ndarray, source: str) -> None:
    """Write lfn_init into a WPS file in place, as CFBM reads it: a 2-D
    float on the fire subgrid. Replaces an existing lfn_init."""
    ny, nx = lfn.shape
    with nc.Dataset(path, "r+") as ds:
        _ensure_dim(ds, _DIM_SN, ny)
        _ensure_dim(ds, _DIM_WE, nx)
        if VAR in ds.variables:
            if ds.variables[VAR].shape != lfn.shape:
                raise ValueError(f"{VAR} in {path} is {ds.variables[VAR].shape}, "
                                 f"the fire grid is {lfn.shape}")
            var = ds.variables[VAR]
        else:
            var = ds.createVariable(VAR, "f4", (_DIM_SN, _DIM_WE), fill_value=False)
            var.MemoryOrder = "XY "
            var.units = "m"
        var.description = (f"Signed distance to the observed fire perimeter, negative "
                           f"inside; source: {source}")
        var[:] = lfn
