import logging
import os
import uuid

import pytest

# Render Qt widgets without opening real windows (works in CI and headless).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Keep every test away from the real %LOCALAPPDATA%\\Drivion, real secrets
    and a real running Drivion (unique single-instance name per test)."""
    for name in list(os.environ):
        if name.startswith("DRIVION_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("DRIVION_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DRIVION_INSTANCE_ID", f"DrivionTest-{uuid.uuid4().hex}")
    # Never sleep, restart or shut down the computer from a test, even by accident:
    # the real power backend refuses to act while this is set.
    monkeypatch.setenv("DRIVION_POWER_DRY_RUN", "1")
    # Never call a real AI provider from a test: no network, no quota spent.
    monkeypatch.setenv("DRIVION_LLM_OFFLINE", "1")
    yield
    root = logging.getLogger()
    for handler in list(root.handlers):
        if not type(handler).__module__.startswith("_pytest"):
            root.removeHandler(handler)
            handler.close()
