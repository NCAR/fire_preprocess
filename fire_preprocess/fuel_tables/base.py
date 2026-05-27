"""Base class for fuel category remapping tables."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import numpy as np


@dataclass
class FuelTable:
    """Maps source raster values (LANDFIRE codes) to CFBM NFUEL_CAT values.

    Attributes:
        name:           short identifier used on the command line
        description:    human-readable description
        nodata_values:  source values that represent non-burnable or missing data
        nodata_out:     NFUEL_CAT value assigned to all nodata pixels (WRF-FIRE
                        convention: 14 = no fuel for Anderson-13 tables)
        remap:          optional dict {source_val: dest_val}; if None the source
                        values are passed through unchanged (suitable for FBFM13
                        where LANDFIRE codes 1-13 already match CFBM)
    """
    name: str
    description: str
    nodata_values: List[int]
    nodata_out: int = 14
    remap: Optional[Dict[int, int]] = None

    def apply(self, data: np.ndarray) -> np.ndarray:
        """Return a float32 array with source fuel codes mapped to WRF values.

        Pixels whose source value is in *nodata_values* — or that were left
        unmapped by a partial *remap* dict — are set to *nodata_out*.
        """
        out = data.astype(np.float32)

        if self.remap is not None:
            remapped = np.full_like(out, self.nodata_out)
            for src, dst in self.remap.items():
                remapped[out == src] = float(dst)
            out = remapped

        for nv in self.nodata_values:
            out[out == float(nv)] = float(self.nodata_out)

        return out
