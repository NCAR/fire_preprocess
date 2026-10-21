"""Compute fire subgrid dimensions and rasterio affine transform.

Existing WPS fire-subgrid dimensions determine the output size. An
unrefined grid can use the atmospheric mass-point count directly. When
subgrid dimensions are absent, construct the padded grid from the
atmospheric staggered point count (e_we / e_sn):

  nx_fire = e_we * sr_x = (nx_mass + 1) * sr_x
  ny_fire = e_sn * sr_y = (ny_mass + 1) * sr_y

Both NFUEL_CAT and ZSF are written on this same grid with dimensions
south_north_subgrid × west_east_subgrid.

The SW corner of the fire grid coincides with the SW staggered corner of
the atmospheric domain, i.e., half an atmospheric grid cell SW of the SW
atmospheric mass point.
"""
from dataclasses import dataclass
from rasterio.transform import from_origin
from .wrf_domain import WRFDomain


@dataclass
class FireGrid:
    nx_fire: int
    ny_fire: int
    dx: float        # fire cell spacing (meters), west-east
    dy: float        # fire cell spacing (meters), south-north
    transform: object  # affine.Affine for rasterio reprojection
    crs: object      # pyproj.CRS of the fire grid


def _fire_dimension(n_mass: int, ratio: int, existing: int | None,
                    name: str) -> int:
    """Retain a WPS extent only when it matches the requested refinement."""
    padded = (n_mass + 1) * ratio
    if existing is None:
        return padded
    # Ratio-one geogrids may omit the northern/eastern padding. Refined
    # grids must still agree with the requested refinement and WPS extent.
    if existing == padded or (ratio == 1 and existing == n_mass):
        return existing
    raise ValueError(
        f"Dimension '{name}' has size {existing}, incompatible with "
        f"{n_mass} atmospheric mass points and subgrid ratio {ratio}. "
        "Check that the requested subgrid ratios match the WPS file."
    )


def build_fire_grid(domain: WRFDomain) -> FireGrid:
    """Use existing WPS subgrid dimensions, or construct a padded fire grid."""
    dx_f = domain.dx / domain.sr_x
    dy_f = domain.dy / domain.sr_y

    nx_fire = _fire_dimension(domain.nx, domain.sr_x, domain.nx_fire,
                             "west_east_subgrid")
    ny_fire = _fire_dimension(domain.ny, domain.sr_y, domain.ny_fire,
                             "south_north_subgrid")

    x0 = domain.x_fire_sw  # west edge of SW fire cell (= SW staggered atm corner)
    y0 = domain.y_fire_sw  # south edge of SW fire cell

    # rasterio origin = top-left corner of top-left pixel
    #   west  = x0               (left edge of col 0)
    #   north = y0 + ny_fire*dy_f (top edge of northernmost row)
    transform = from_origin(
        west=x0,
        north=y0 + ny_fire * dy_f,
        xsize=dx_f,
        ysize=dy_f,
    )

    return FireGrid(
        nx_fire=nx_fire, ny_fire=ny_fire,
        dx=dx_f, dy=dy_f,
        transform=transform,
        crs=domain.crs,
    )
