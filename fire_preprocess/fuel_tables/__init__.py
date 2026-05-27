"""Fuel table definitions for CFBM NFUEL_CAT remapping."""
from .registry import get_fuel_table, list_fuel_tables
from .base import FuelTable

__all__ = ["get_fuel_table", "list_fuel_tables", "FuelTable"]
