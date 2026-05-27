"""Scott & Burgan 40-category fire behavior fuel model (FBFM40).

LANDFIRE distributes FBFM40 with a three-digit encoding:
  GR1-GR9   → 101-109  (grass)
  GS1-GS4   → 121-124  (grass-shrub)
  SH1-SH9   → 141-149  (shrub)
  TU1-TU5   → 161-165  (timber understory)
  TL1-TL9   → 181-189  (timber litter)
  SB1-SB4   → 201-204  (slash)
  NB/non-burnable → 91-99

Two tables are provided:

  fbfm40              Passes LANDFIRE 3-digit codes through unchanged.
                      CFBM internally calls Crosswalk_from_scottburgan_to_anderson
                      (share/fuel_mod.F90) to convert these to Anderson 13 at runtime.

  fbfm40_to_anderson13  Pre-applies the same crosswalk that WRF-FIRE uses internally,
                      producing Anderson 13 output.  The mapping exactly mirrors
                      Crosswalk_from_scottburgan_to_anderson in fuel_mod.F90.

References:
  Scott & Burgan (2005), Standard fire behavior fuel models: a comprehensive
  set for use with Rothermel's surface fire spread model. USDA FS RMRS-GTR-153.
  NCAR/fire_behavior: share/fuel_mod.F90, Crosswalk_from_scottburgan_to_anderson
"""
from .base import FuelTable

FBFM40 = FuelTable(
    name="fbfm40",
    description="Scott & Burgan 40-category fuel model — LANDFIRE 3-digit codes passed through for CFBM internal crosswalk",
    nodata_values=[0, -9999, 32767],
    nodata_out=14,
    remap=None,
)

# Exact crosswalk from Crosswalk_from_scottburgan_to_anderson in
# NCAR/fire_behavior share/fuel_mod.F90.
_LANDFIRE_TO_ANDERSON13 = {
    # Anderson 1 — Short Grass
    101: 1,  104: 1,  107: 1,
    # Anderson 2 — Timber Grass and Understory
    102: 2,  121: 2,  122: 2,  123: 2,  124: 2,
    # Anderson 3 — Tall Grass
    103: 3,  105: 3,  106: 3,  108: 3,  109: 3,
    # Anderson 4 — Chaparral
    145: 4,  147: 4,
    # Anderson 5 — Brush
    142: 5,
    # Anderson 6 — Dormant Brush, Hardwood Slash
    141: 6,  146: 6,
    # Anderson 7 — Southern Rough
    143: 7,  144: 7,  148: 7,  149: 7,
    # Anderson 8 — Compact Timber Litter
    181: 8,  183: 8,  184: 8,  187: 8,
    # Anderson 9 — Hardwood Litter
    182: 9,  186: 9,  188: 9,  189: 9,
    # Anderson 10 — Timber (Litter and Understory)
    161: 10, 162: 10, 163: 10, 164: 10, 165: 10,
    # Anderson 11 — Light Logging Slash
    185: 11, 201: 11,
    # Anderson 12 — Medium Logging Slash
    202: 12,
    # Anderson 13 — Heavy Logging Slash
    203: 13, 204: 13,
}

FBFM40_TO_ANDERSON13 = FuelTable(
    name="fbfm40_to_anderson13",
    description="Scott & Burgan 40 remapped to Anderson 13 — exact crosswalk from fire_behavior/fuel_mod.F90",
    nodata_values=[0, 91, 92, 93, 98, 99, -9999, 32767],
    nodata_out=14,
    remap=_LANDFIRE_TO_ANDERSON13,
)
