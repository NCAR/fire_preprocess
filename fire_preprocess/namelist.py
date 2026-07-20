"""Parse namelist.wps to extract WRF domain and fire subgrid parameters."""
import f90nml


def _is_sequence(value):
    """Return True for per-domain namelist arrays."""
    return isinstance(value, (list, tuple))


def read_namelist_wps(path):
    """Return a flat dict of all namelist.wps parameters (share + geogrid merged)."""
    nml = f90nml.read(path)
    params = {}
    for section in ("share", "geogrid"):
        params.update(nml.get(section, {}))
    return params


def _scalar(value, index=0):
    """Return a scalar from a value that may be a list (per-domain array)."""
    if _is_sequence(value):
        return value[index]
    return value


def _effective_grid_spacing(params, domain_index, axis):
    """Return domain grid spacing, deriving nests from parent_grid_ratio.

    WPS normally stores dx/dy as scalar parent-domain spacings.  For nested
    domains, the child spacing is the parent spacing divided by the refinement
    ratio along the parent chain.
    """
    value = params[axis]
    if _is_sequence(value):
        return float(_scalar(value, domain_index))

    if domain_index == 0:
        return float(value)

    parent_ids = params.get("parent_id")
    parent_ratios = params.get("parent_grid_ratio")
    if parent_ids is None or parent_ratios is None:
        raise ValueError(
            f"Cannot derive nested-domain {axis}: parent_id and "
            "parent_grid_ratio are required when dx/dy are scalar."
        )

    parent_index = int(_scalar(parent_ids, domain_index)) - 1
    if parent_index == domain_index:
        raise ValueError(f"Domain {domain_index + 1} cannot be its own parent.")

    parent_spacing = _effective_grid_spacing(params, parent_index, axis)
    ratio = float(_scalar(parent_ratios, domain_index))
    return parent_spacing / ratio


def _parent_grid_info(params, domain_index):
    """Return nested-domain parent metadata, or None for the root domain."""
    if domain_index == 0:
        return None

    parent_index = int(_scalar(params["parent_id"], domain_index)) - 1
    ratio = int(_scalar(params["parent_grid_ratio"], domain_index))
    i_start = int(_scalar(params["i_parent_start"], domain_index))
    j_start = int(_scalar(params["j_parent_start"], domain_index))
    return {
        "parent_index": parent_index,
        "parent_grid_ratio": ratio,
        "i_parent_start": i_start,
        "j_parent_start": j_start,
    }


def _mass_offset_from_root(params, domain_index, axis):
    """Return nested-domain SW mass-point offset from the root mass grid."""
    if domain_index == 0:
        return 0.0

    parent = _parent_grid_info(params, domain_index)
    parent_index = parent["parent_index"]
    parent_spacing = _effective_grid_spacing(params, parent_index, axis)
    start_key = "i_parent_start" if axis == "dx" else "j_parent_start"

    # WPS parent starts are 1-based parent-domain mass-grid indices.  Convert
    # them to a zero-based offset, then accumulate through any deeper nests.
    parent_offset = _mass_offset_from_root(params, parent_index, axis)
    return parent_offset + (parent[start_key] - 1) * parent_spacing


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
    root_e_we = int(_scalar(params["e_we"], 0))
    root_e_sn = int(_scalar(params["e_sn"], 0))

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
        "ref_x": float(params.get("ref_x", (root_e_we + 1) / 2.0)),
        "ref_y": float(params.get("ref_y", (root_e_sn + 1) / 2.0)),
        "root_dx": _effective_grid_spacing(params, 0, "dx"),
        "root_dy": _effective_grid_spacing(params, 0, "dy"),
        "x_mass_offset_from_root": _mass_offset_from_root(params, domain_index, "dx"),
        "y_mass_offset_from_root": _mass_offset_from_root(params, domain_index, "dy"),
        "dx": _effective_grid_spacing(params, domain_index, "dx"),
        "dy": _effective_grid_spacing(params, domain_index, "dy"),
        "e_we": e_we,
        "e_sn": e_sn,
        "parent": _parent_grid_info(params, domain_index),
    }
