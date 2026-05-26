"""Extract WRF domain geometry and build the WRF map projection.

WRF uses a perfect sphere (R = 6370000 m), not WGS84, for all of its
map projections. Using WGS84 here would produce sub-pixel registration
errors that grow toward domain edges.
"""
from dataclasses import dataclass
import netCDF4 as nc
import numpy as np
from pyproj import CRS, Transformer

WRF_SPHERE_RADIUS = 6370000.0  # meters, matches WRF's MAP_FACTOR


@dataclass
class WRFDomain:
    nx: int           # atmospheric mass points, west-east  (= e_we - 1)
    ny: int           # atmospheric mass points, south-north (= e_sn - 1)
    dx: float         # atmospheric grid spacing, meters (west-east)
    dy: float         # atmospheric grid spacing, meters (south-north)
    map_proj: int     # 1=LCC, 2=Polar Stereographic, 3=Mercator, 6=Lat-Lon
    truelat1: float
    truelat2: float
    stand_lon: float
    crs: CRS          # pyproj CRS for the WRF map projection
    x_fire_sw: float  # x of SW fire-grid corner in WRF projection coords (m)
    y_fire_sw: float  # y of SW fire-grid corner in WRF projection coords (m)
    sr_x: int         # fire subgrid refinement ratio, west-east
    sr_y: int         # fire subgrid refinement ratio, south-north


def build_wrf_crs(map_proj, truelat1, truelat2, stand_lon):
    """Build a pyproj CRS matching WRF's internal map projection."""
    sphere = f"+a={WRF_SPHERE_RADIUS} +b={WRF_SPHERE_RADIUS}"

    if map_proj == 1:
        proj_str = (
            f"+proj=lcc +lat_1={truelat1} +lat_2={truelat2} "
            f"+lat_0={truelat1} +lon_0={stand_lon} "
            f"+x_0=0 +y_0=0 {sphere} +units=m +no_defs"
        )
    elif map_proj == 2:
        lat_0 = 90.0 if truelat1 >= 0 else -90.0
        proj_str = (
            f"+proj=stere +lat_ts={truelat1} +lat_0={lat_0} "
            f"+lon_0={stand_lon} +x_0=0 +y_0=0 {sphere} +units=m +no_defs"
        )
    elif map_proj == 3:
        proj_str = (
            f"+proj=merc +lat_ts={truelat1} +lon_0={stand_lon} "
            f"+x_0=0 +y_0=0 {sphere} +units=m +no_defs"
        )
    elif map_proj == 6:
        proj_str = f"+proj=longlat {sphere} +no_defs"
    else:
        raise ValueError(f"Unsupported map_proj: {map_proj}. Supported: 1 (LCC), 2 (Polar), 3 (Mercator), 6 (Lat-Lon)")

    return CRS.from_proj4(proj_str)


def _sw_corner_from_wps(ds, crs):
    """Return (x_sw_mass, y_sw_mass) in WRF proj coords from WPS arrays."""
    if "XLAT_M" not in ds.variables or "XLONG_M" not in ds.variables:
        raise KeyError("netCDF file is missing XLAT_M / XLONG_M variables")

    lat_sw = float(ds.variables["XLAT_M"][0, 0, 0])
    lon_sw = float(ds.variables["XLONG_M"][0, 0, 0])

    # Use WRF's sphere for the geographic source CRS so the transformer is
    # internally consistent with the projection definition.
    geo_crs = CRS.from_proj4(f"+proj=longlat +a={WRF_SPHERE_RADIUS} +b={WRF_SPHERE_RADIUS} +no_defs")
    transformer = Transformer.from_crs(geo_crs, crs, always_xy=True)
    return transformer.transform(lon_sw, lat_sw)


def _sw_corner_from_namelist(params, crs):
    """Compute (x_sw_mass, y_sw_mass) from namelist.wps parameters."""
    geo_crs = CRS.from_proj4(f"+proj=longlat +a={WRF_SPHERE_RADIUS} +b={WRF_SPHERE_RADIUS} +no_defs")
    transformer = Transformer.from_crs(geo_crs, crs, always_xy=True)

    x_ref, y_ref = transformer.transform(params["ref_lon"], params["ref_lat"])

    # ref_x/ref_y are 1-indexed staggered grid positions that map to ref_lat/ref_lon.
    # Convert to 0-indexed mass point offset.
    i_ref = params["ref_x"] - 1.0   # staggered i → subtract 0.5 for mass point
    j_ref = params["ref_y"] - 1.0   # staggered j
    i_ref_mass = i_ref - 0.5
    j_ref_mass = j_ref - 0.5

    x_sw_mass = x_ref - i_ref_mass * params["dx"]
    y_sw_mass = y_ref - j_ref_mass * params["dy"]
    return x_sw_mass, y_sw_mass


def read_domain_from_file(file_path, sr_x, sr_y, namelist_params=None):
    """Build a WRFDomain by reading a WPS netCDF file.

    Args:
        file_path: path to any met_em*.nc or geo_em*.nc file for the domain
        sr_x, sr_y: fire subgrid ratios from namelist.wps
        namelist_params: optional dict from namelist.get_domain_params(), used
                         as fallback if XLAT_M/XLONG_M are absent

    Returns:
        WRFDomain dataclass
    """
    with nc.Dataset(file_path) as ds:
        attrs = {k: ds.getncattr(k) for k in ds.ncattrs()}

        map_proj = int(attrs["MAP_PROJ"])
        truelat1 = float(attrs.get("TRUELAT1", 0.0))
        truelat2 = float(attrs.get("TRUELAT2", 0.0))
        stand_lon = float(attrs["STAND_LON"])
        dx = float(attrs["DX"])
        dy = float(attrs["DY"])

        crs = build_wrf_crs(map_proj, truelat1, truelat2, stand_lon)

        try:
            x_sw_mass, y_sw_mass = _sw_corner_from_wps(ds, crs)
            ny = ds.variables["XLAT_M"].shape[1]
            nx = ds.variables["XLAT_M"].shape[2]
        except KeyError:
            if namelist_params is None:
                raise RuntimeError(
                    "XLAT_M/XLONG_M not found in file and no namelist_params supplied"
                )
            x_sw_mass, y_sw_mass = _sw_corner_from_namelist(namelist_params, crs)
            nx = namelist_params["e_we"] - 1
            ny = namelist_params["e_sn"] - 1

    # The fire grid's SW corner is half an atmospheric cell SW of the SW mass point.
    x_fire_sw = x_sw_mass - dx / 2.0
    y_fire_sw = y_sw_mass - dy / 2.0

    return WRFDomain(
        nx=nx, ny=ny, dx=dx, dy=dy,
        map_proj=map_proj, truelat1=truelat1, truelat2=truelat2,
        stand_lon=stand_lon, crs=crs,
        x_fire_sw=x_fire_sw, y_fire_sw=y_fire_sw,
        sr_x=sr_x, sr_y=sr_y,
    )
