#!/usr/bin/env python3
# Copyright 2026      Research Applications Laboratory (RAL),
#                     National Center for Atmospheric Research (NCAR),
#                     University Corporation for Atmospheric Research (UCAR)
#
#--------------------------------------------------------------------------------
# Created by Maria Frediani (frediani@ucar.edu) on 2026-08-25
#--------------------------------------------------------------------------------
# run /glade/work/frediani/casper/anaconda3/envs/py314/bin/python fire_preprocess.py --help
#
"""Construct full-domain fire fields from clipped high-resolution rasters."""

from __future__ import annotations

import netCDF4 as nc
import numpy as np


#--------------------------------------------------------------------------------
# Atmospheric terrain background
#--------------------------------------------------------------------------------

def read_atmospheric_terrain(path: str) -> tuple[np.ndarray, str]:
    """Read finite mass-grid terrain from a WPS output file."""
    with nc.Dataset(path) as dataset:
        terrain_name = "HGT_M"
        if terrain_name not in dataset.variables:
            raise KeyError(f"{path} does not contain HGT_M")

        terrain_var = dataset.variables[terrain_name]
        terrain = np.ma.filled(terrain_var[0], np.nan).astype(np.float32)

    if terrain.ndim != 2 or not np.isfinite(terrain).all():
        raise ValueError(
            f"{terrain_name} in {path} must be a finite two-dimensional field"
        )
    return terrain, terrain_name


def _linear_coordinates(source_size: int, ratio: int) -> np.ndarray:
    """Return fire-cell center coordinates in atmospheric mass-grid units."""
    active_size = source_size * ratio
    return (np.arange(active_size) - 0.5 * (ratio - 1)) / ratio


def _interpolate_axis(values: np.ndarray, coordinates: np.ndarray, axis: int) -> np.ndarray:
    """Interpolate along one axis and linearly continue through boundary cells."""
    source = np.moveaxis(np.asarray(values, dtype=np.float32), axis, -1)
    source_size = source.shape[-1]
    if source_size < 2:
        raise ValueError("atmospheric terrain needs at least two points per axis")

    lower = np.floor(coordinates).astype(np.int64)
    lower_clipped = np.clip(lower, 0, source_size - 2)
    upper_clipped = lower_clipped + 1
    fraction = coordinates - lower_clipped

    result = (
        np.take(source, lower_clipped, axis=-1) * (1.0 - fraction)
        + np.take(source, upper_clipped, axis=-1) * fraction
    )
    return np.moveaxis(result.astype(np.float32), -1, axis)


def interpolate_hgt_to_fire_grid(
    terrain: np.ndarray,
    sr_x: int,
    sr_y: int,
    output_shape: tuple[int, int],
) -> np.ndarray:
    """Bilinearly interpolate mass-grid HGT onto the complete fire array."""
    terrain_values = np.asarray(terrain, dtype=np.float32)
    if terrain_values.ndim != 2 or not np.isfinite(terrain_values).all():
        raise ValueError("atmospheric terrain must be a finite two-dimensional field")

    y_coordinates = _linear_coordinates(terrain_values.shape[0], sr_y)
    x_coordinates = _linear_coordinates(terrain_values.shape[1], sr_x)
    interpolated_x = _interpolate_axis(terrain_values, x_coordinates, axis=1)
    active = _interpolate_axis(interpolated_x, y_coordinates, axis=0)

    expected_shape = (
        (terrain_values.shape[0] + 1) * sr_y,
        (terrain_values.shape[1] + 1) * sr_x,
    )
    if output_shape != expected_shape:
        raise ValueError(
            f"fire grid shape {output_shape} does not match expected {expected_shape}"
        )

    background = np.empty(output_shape, dtype=np.float32)
    active_ny, active_nx = active.shape
    background[:active_ny, :active_nx] = active
    background[:active_ny, active_nx:] = active[:, -1, None]
    background[active_ny:, :] = background[active_ny - 1, :]
    return background


#--------------------------------------------------------------------------------
# High-resolution fire-area overlay
#--------------------------------------------------------------------------------

def merge_fire_coverage(
    nfuel_raw: np.ndarray,
    zsf_raw: np.ndarray,
    fuel_valid: np.ndarray,
    dem_valid: np.ndarray,
    terrain_background: np.ndarray,
    fuel_table,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Apply high-resolution data only within joint fuel and terrain coverage."""
    shape = terrain_background.shape
    inputs = (nfuel_raw, zsf_raw, fuel_valid, dem_valid)
    if any(np.asarray(item).shape != shape for item in inputs):
        raise ValueError("fuel, DEM, masks, and terrain background must share a shape")
    if not np.isfinite(terrain_background).all():
        raise ValueError("interpolated HGT_M background must be finite")

    joint_valid = (
        np.asarray(fuel_valid, dtype=bool)
        & np.asarray(dem_valid, dtype=bool)
        & np.isfinite(nfuel_raw)
        & np.isfinite(zsf_raw)
    )

    nfuel = fuel_table.apply(nfuel_raw)
    nfuel[~joint_valid] = float(fuel_table.nodata_out)

    zsf = np.asarray(terrain_background, dtype=np.float32).copy()
    zsf[joint_valid] = np.asarray(zsf_raw, dtype=np.float32)[joint_valid]
    return nfuel.astype(np.float32), zsf, joint_valid
