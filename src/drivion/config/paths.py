"""Filesystem locations used by Drivion.

Personal data (logs now; face templates later) lives in the per-user
``%LOCALAPPDATA%\\Drivion`` folder, outside the Git repository, so it can
never be committed by accident. ``DRIVION_DATA_DIR`` overrides it (used by tests).

From source, ``config/settings.toml`` and ``.env`` sit in the project. In a
packaged build the program folder may not be writable and could be shared, so
they move to the data folder too.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))  # running from the PyInstaller build
WINDOWED_PROGRAM = "DrivionApp.exe"  # the build's program with no console window
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def data_dir() -> Path:
    override = os.environ.get("DRIVION_DATA_DIR")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Drivion"


def user_files_dir(frozen: bool = FROZEN) -> Path:
    """Where ``config/settings.toml`` and ``.env`` live."""
    return data_dir() if frozen else PROJECT_ROOT


DEFAULT_CONFIG_FILE = user_files_dir() / "config" / "settings.toml"
DEFAULT_ENV_FILE = user_files_dir() / ".env"


def launch_command(*args: str) -> list[str]:
    """How to start Drivion with no console window: the program, then its arguments."""
    program = Path(sys.executable)
    if FROZEN:
        return [str(program.with_name(WINDOWED_PROGRAM)), *args]
    windowless = program.with_name("pythonw.exe")
    return [str(windowless if windowless.exists() else program), "-m", "drivion", *args]


def log_dir() -> Path:
    return data_dir() / "logs"


def models_dir() -> Path:
    return data_dir() / "models"


def face_dir() -> Path:
    """Encrypted face templates. Never inside the repository."""
    return data_dir() / "face"
