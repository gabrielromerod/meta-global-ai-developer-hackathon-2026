"""Intrinsic and extrinsic calibration (FR-036, FR-037)."""

from __future__ import annotations

from pathlib import Path

from vigil.models import Extrinsics, Intrinsics


def calibrate_intrinsics(frames: list[Path], fisheye: bool = False) -> Intrinsics:
    """Stub."""
    raise NotImplementedError("FR-036/FR-037 not implemented")


def calibrate_extrinsics(pairs: list[tuple], k: Intrinsics) -> Extrinsics:
    """Stub."""
    raise NotImplementedError("FR-036/FR-037 not implemented")
