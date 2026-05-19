"""Compute fire subgrid dimensions and rasterio affine transforms.

Fire grid layout relative to the atmospheric mass grid:
  - Atmospheric mass points: nx × ny, spacing dx × dy
  - Fire mass grid (NFUEL_CAT): nx*sr_x × ny*sr_y, spacing dx/sr_x × dy/sr_y
  - Fire staggered grid (ZSF):  (nx*sr_x+1) × (ny*sr_y+1), same spacing

The SW corner of the fire grid (both mass and staggered) coincides with the
SW corner of the first atmospheric grid cell, i.e., half an atmospheric grid
cell SW of the SW atmospheric mass point.

Rasterio convention: the affine transform's origin is the *top-left corner*
of the *top-left pixel*.  For cell-centred data (NFUEL_CAT mass points), the
origin is shifted inward by half a cell so that pixel centres align with the
actual fire grid points.  ZSF staggered points are treated as pixel centres of
a shifted grid.
"""
from dataclasses import dataclass
from rasterio.transform import from_origin
from .wrf_domain import WRFDomain


@dataclass
class FireGrid:
    # Mass grid — used for NFUEL_CAT
    nx_mass: int
    ny_mass: int
    dx: float           # fire cell spacing (metres), west-east
    dy: float           # fire cell spacing (metres), south-north
    transform_mass: object  # affine.Affine: pixel origin at top-left corner

    # Staggered grid — used for ZSF (one extra point in each direction)
    nx_stag: int
    ny_stag: int
    transform_stag: object  # affine.Affine: pixel origin at top-left corner

    crs: object         # pyproj.CRS of the fire grid


def build_fire_grid(domain: WRFDomain) -> FireGrid:
    """Derive the FireGrid from a WRFDomain."""
    dx_f = domain.dx / domain.sr_x
    dy_f = domain.dy / domain.sr_y

    nx_mass = domain.nx * domain.sr_x
    ny_mass = domain.ny * domain.sr_y
    nx_stag = nx_mass + 1
    ny_stag = ny_mass + 1

    x0 = domain.x_fire_sw  # west edge of SW fire cell
    y0 = domain.y_fire_sw  # south edge of SW fire cell

    # ── Mass grid (NFUEL_CAT) ────────────────────────────────────────────────
    # Pixel centres are at: x0 + (i+0.5)*dx_f,  y0 + (j+0.5)*dy_f
    # rasterio origin = top-left corner of top-left pixel
    #   west  = x0  (left edge of col 0)
    #   north = y0 + ny_mass * dy_f  (top edge of row 0, i.e., northernmost row)
    transform_mass = from_origin(
        west=x0,
        north=y0 + ny_mass * dy_f,
        xsize=dx_f,
        ysize=dy_f,
    )

    # ── Staggered grid (ZSF) ─────────────────────────────────────────────────
    # Staggered points are at: x0 + i*dx_f,  y0 + j*dy_f (i,j = 0..nx/ny_stag-1)
    # Treat each point as a pixel centre → left edge of col 0 = x0 - dx_f/2
    #                                    → top  edge of row 0 = y0 + ny_mass*dy_f + dy_f/2
    transform_stag = from_origin(
        west=x0 - dx_f / 2.0,
        north=y0 + ny_mass * dy_f + dy_f / 2.0,
        xsize=dx_f,
        ysize=dy_f,
    )

    return FireGrid(
        nx_mass=nx_mass, ny_mass=ny_mass,
        dx=dx_f, dy=dy_f,
        transform_mass=transform_mass,
        nx_stag=nx_stag, ny_stag=ny_stag,
        transform_stag=transform_stag,
        crs=domain.crs,
    )
