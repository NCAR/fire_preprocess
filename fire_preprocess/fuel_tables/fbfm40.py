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

  fbfm40              Renumbers LANDFIRE codes to 1-40 for use with a WRF
                      build that includes the 40-category fuel table
                      (NB_FUEL_CATS=40 in phys/module_fr_fire_phys.F).

  fbfm40_to_anderson13  Approximate crosswalk from FBFM40 to the standard
                      Anderson 13 table.  Use this when WRF is compiled with
                      the default NB_FUEL_CATS=14.  The crosswalk is based on
                      structural similarity; validate against local conditions.

References:
  Scott & Burgan (2005), Standard fire behavior fuel models: a comprehensive
  set for use with Rothermel's surface fire spread model. USDA FS RMRS-GTR-153.
"""
from .base import FuelTable

# LANDFIRE 3-digit codes → sequential 1-40 for WRF FBFM40 build
_LANDFIRE_TO_WRF40 = {
    # GR (grass)
    101: 1,  102: 2,  103: 3,  104: 4,  105: 5,
    106: 6,  107: 7,  108: 8,  109: 9,
    # GS (grass-shrub)
    121: 10, 122: 11, 123: 12, 124: 13,
    # SH (shrub)
    141: 14, 142: 15, 143: 16, 144: 17, 145: 18,
    146: 19, 147: 20, 148: 21, 149: 22,
    # TU (timber understory)
    161: 23, 162: 24, 163: 25, 164: 26, 165: 27,
    # TL (timber litter)
    181: 28, 182: 29, 183: 30, 184: 31, 185: 32,
    186: 33, 187: 34, 188: 35, 189: 36,
    # SB (slash)
    201: 37, 202: 38, 203: 39, 204: 40,
}

FBFM40 = FuelTable(
    name="fbfm40",
    description="Scott & Burgan 40-category fuel model (requires WRF NB_FUEL_CATS=40)",
    nodata_values=[0, 91, 92, 93, 98, 99, -9999, 32767],
    nodata_out=99,  # WRF-FIRE non-burnable placeholder for 40-cat table
    remap=_LANDFIRE_TO_WRF40,
)

# Approximate FBFM40 → Anderson 13 crosswalk.
# Based on structural similarity (grass/shrub/timber/slash groupings).
# This crosswalk is approximate — review against local conditions.
_LANDFIRE_TO_ANDERSON13 = {
    # GR → Anderson 1 (Short Grass) or 3 (Tall Grass)
    101: 1,  102: 1,  103: 2,  104: 3,  105: 3,
    106: 3,  107: 3,  108: 3,  109: 3,
    # GS → Anderson 2 (Timber Grass) or 5 (Brush)
    121: 2,  122: 2,  123: 5,  124: 5,
    # SH → Anderson 5 (Brush) or 6 (Dormant Brush)
    141: 5,  142: 6,  143: 5,  144: 6,  145: 6,
    146: 6,  147: 6,  148: 6,  149: 6,
    # TU → Anderson 9 (Hardwood Litter)
    161: 9,  162: 9,  163: 9,  164: 9,  165: 9,
    # TL → Anderson 8 (Compact Timber Litter) or 9 (Hardwood)
    181: 8,  182: 8,  183: 8,  184: 8,  185: 8,
    186: 9,  187: 9,  188: 9,  189: 9,
    # SB → Anderson 11 (Light Slash) through 13 (Heavy Slash)
    201: 11, 202: 12, 203: 13, 204: 13,
}

FBFM40_TO_ANDERSON13 = FuelTable(
    name="fbfm40_to_anderson13",
    description="Scott & Burgan 40 remapped to Anderson 13 (approximate crosswalk)",
    nodata_values=[0, 91, 92, 93, 98, 99, -9999, 32767],
    nodata_out=14,
    remap=_LANDFIRE_TO_ANDERSON13,
)
