"""Compute fire subgrid dimensions and rasterio affine transform.

WPS uses the atmospheric *staggered* point count (e_we / e_sn) — not the
mass point count — to determine the fire subgrid size:

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
    dx: float        # fire cell spacing (metres), west-east
    dy: float        # fire cell spacing (metres), south-north
    transform: object  # affine.Affine for rasterio reprojection
    crs: object      # pyproj.CRS of the fire grid


def build_fire_grid(domain: WRFDomain) -> FireGrid:
    """Derive the FireGrid from a WRFDomain.

    Fire grid size follows WPS convention: (nx_mass + 1) * sr, which equals
    e_we * sr_x and e_sn * sr_y.
    """
    dx_f = domain.dx / domain.sr_x
    dy_f = domain.dy / domain.sr_y

    # +1 because WPS sizes the fire grid on the staggered atmospheric count
    nx_fire = (domain.nx + 1) * domain.sr_x
    ny_fire = (domain.ny + 1) * domain.sr_y

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
