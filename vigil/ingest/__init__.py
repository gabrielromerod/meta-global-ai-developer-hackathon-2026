"""Ingest: config, clock sync, privacy masking, windowing, motion gate (FR-001 to FR-005).

Modules: ``config`` (FR-001), ``sync`` (FR-002), ``privacy`` (FR-003), ``windows``
(FR-004), ``motion`` (FR-005) and ``media`` (ffprobe and the masked transcode they share).
Only the config API is re-exported here so importing the package stays light (no OpenCV).
"""

from vigil.ingest.config import (
    ConfigError,
    ConfigFileError,
    ConfigSchemaError,
    DuplicateIdError,
    GeometryError,
    TopologyError,
    UnknownCameraError,
    UnknownExitError,
    UnknownZoneError,
    find_geometry,
    load_config,
    privacy_polygons,
    validate_config,
)

__all__ = [
    "ConfigError",
    "ConfigFileError",
    "ConfigSchemaError",
    "DuplicateIdError",
    "GeometryError",
    "TopologyError",
    "UnknownCameraError",
    "UnknownExitError",
    "UnknownZoneError",
    "find_geometry",
    "load_config",
    "privacy_polygons",
    "validate_config",
]
