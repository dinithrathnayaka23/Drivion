"""Filesystem locations used by Drivion.

Personal data (logs now; face templates later) lives in the per-user
``%LOCALAPPDATA%\\Drivion`` folder, outside the Git repository, so it can
never be committed by accident. ``DRIVION_DATA_DIR`` overrides it (used by tests).
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_FILE = PROJECT_ROOT / "config" / "settings.toml"
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"


def data_dir() -> Path:
    override = os.environ.get("DRIVION_DATA_DIR")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Drivion"


def log_dir() -> Path:
    return data_dir() / "logs"


def models_dir() -> Path:
    return data_dir() / "models"
