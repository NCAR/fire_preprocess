"""Parse namelist.wps to extract WRF domain and fire subgrid parameters."""
import f90nml


def read_namelist_wps(path):
    """Return a flat dict of all namelist.wps parameters (share + geogrid merged)."""
    nml = f90nml.read(path)
    params = {}
    for section in ("share", "geogrid"):
        params.update(nml.get(section, {}))
    return params


def _scalar(value, index=0):
    """Return a scalar from a value that may be a list (per-domain array)."""
    if isinstance(value, (list, tuple)):
        return value[index]
    return value


def get_fire_subgrid_ratios(path, domain_index=0):
    """Return (sr_x, sr_y) fire subgrid refinement ratios from namelist.wps.

    Args:
        path: path to namelist.wps
        domain_index: 0-based domain index (default 0 = first domain)

    Returns:
        (sr_x, sr_y) as integers; defaults to (1, 1) if not present
    """
    params = read_namelist_wps(path)
    sr_x = int(_scalar(params.get("subgrid_ratio_x", 1), domain_index))
    sr_y = int(_scalar(params.get("subgrid_ratio_y", 1), domain_index))
    return sr_x, sr_y


def get_domain_params(path, domain_index=0):
    """Return a dict of domain geometry parameters for one domain.

    Returned keys: map_proj (int), truelat1, truelat2, stand_lon,
    ref_lat, ref_lon, ref_x, ref_y, dx, dy, e_we, e_sn.
    ref_x/ref_y default to the domain centre if not in the namelist.
    """
    params = read_namelist_wps(path)

    e_we = int(_scalar(params["e_we"], domain_index))
    e_sn = int(_scalar(params["e_sn"], domain_index))

    proj_map = {"lambert": 1, "polar": 2, "mercator": 3, "lat-lon": 6, "latlong": 6}
    raw_proj = str(params.get("map_proj", "lambert")).strip().lower().strip("'\"")
    map_proj = proj_map.get(raw_proj, 1)

    return {
        "map_proj": map_proj,
        "truelat1": float(params.get("truelat1", 0.0)),
        "truelat2": float(params.get("truelat2", 0.0)),
        "stand_lon": float(params.get("stand_lon", 0.0)),
        "ref_lat": float(params.get("ref_lat", 0.0)),
        "ref_lon": float(params.get("ref_lon", 0.0)),
        "ref_x": float(params.get("ref_x", (e_we + 1) / 2.0)),
        "ref_y": float(params.get("ref_y", (e_sn + 1) / 2.0)),
        "dx": float(_scalar(params["dx"], domain_index)),
        "dy": float(_scalar(params["dy"], domain_index)),
        "e_we": e_we,
        "e_sn": e_sn,
    }
