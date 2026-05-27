"""Anderson 13-category fire behavior fuel model (FBFM13).

LANDFIRE distributes FBFM13 data with values 1-13 for burnable fuels and
91-99 for non-burnable categories (urban, snow, agriculture, water, barren).
CFBM's default fuel table uses categories 1-13 with 14 as "no fuel", so
LANDFIRE FBFM13 values can be passed through with only the non-burnable codes
remapped.

CFBM fuel table reference:
  Anderson (1982), Aids to determining fuel models for estimating fire behavior.
  USDA Forest Service Gen. Tech. Rep. INT-122.
"""
from .base import FuelTable

FBFM13 = FuelTable(
    name="fbfm13",
    description="Anderson 13-category fuel model (FBFM13) — direct LANDFIRE passthrough",
    # LANDFIRE non-burnable and fill codes; all map to nodata_out=14.
    # 32767 is LANDFIRE's fill value for pixels outside the valid data extent.
    nodata_values=[0, 91, 92, 93, 98, 99, -9999, 32767],
    nodata_out=14,
    remap=None,  # values 1-13 already match CFBM
)
