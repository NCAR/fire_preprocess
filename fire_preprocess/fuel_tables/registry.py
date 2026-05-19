"""Fuel table registry and factory."""
import csv
import os
from .base import FuelTable
from .fbfm13 import FBFM13
from .fbfm40 import FBFM40, FBFM40_TO_ANDERSON13

_REGISTRY: dict[str, FuelTable] = {
    FBFM13.name: FBFM13,
    FBFM40.name: FBFM40,
    FBFM40_TO_ANDERSON13.name: FBFM40_TO_ANDERSON13,
}


def list_fuel_tables() -> list[str]:
    """Return names of all built-in fuel tables."""
    return list(_REGISTRY.keys())


def get_fuel_table(name_or_path: str) -> FuelTable:
    """Return a FuelTable by name or by loading a CSV file.

    Built-in names: fbfm13, fbfm40, fbfm40_to_anderson13

    Custom CSV format (two columns, header row required):
        source,target
        1,1
        2,2
        91,14
        ...
    Any source value not listed in the CSV is mapped to nodata_out (14).
    """
    if name_or_path in _REGISTRY:
        return _REGISTRY[name_or_path]

    if os.path.isfile(name_or_path):
        return _load_csv_table(name_or_path)

    raise ValueError(
        f"Unknown fuel table '{name_or_path}'.\n"
        f"Built-in tables: {', '.join(list_fuel_tables())}\n"
        f"Or supply a path to a CSV file with 'source' and 'target' columns."
    )


def _load_csv_table(path: str) -> FuelTable:
    remap = {}
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        if "source" not in (reader.fieldnames or []) or "target" not in (reader.fieldnames or []):
            raise ValueError(
                f"CSV fuel table '{path}' must have 'source' and 'target' column headers."
            )
        for row in reader:
            remap[int(row["source"])] = int(row["target"])

    return FuelTable(
        name=f"custom:{os.path.basename(path)}",
        description=f"Custom fuel table loaded from {path}",
        nodata_values=[],  # user's remap should cover all cases
        nodata_out=14,
        remap=remap,
    )
