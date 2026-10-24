import logging
import os

import pytest

# Render Qt widgets without opening real windows (works in CI and headless).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Keep every test away from the real %LOCALAPPDATA%\\Drivion and real secrets."""
    monkeypatch.setenv("DRIVION_DATA_DIR", str(tmp_path / "data"))
    for name in list(os.environ):
        if name.startswith("DRIVION_") and name != "DRIVION_DATA_DIR":
            monkeypatch.delenv(name)
    yield
    root = logging.getLogger()
    for handler in list(root.handlers):
        if not type(handler).__module__.startswith("_pytest"):
            root.removeHandler(handler)
            handler.close()
