import gc
import logging
import os
import sys
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
    # Never change what really starts at login from a test.
    autostart_key = f"Software\\DrivionTest-{uuid.uuid4().hex}"
    monkeypatch.setenv("DRIVION_AUTOSTART_KEY", autostart_key)
    yield
    if sys.platform == "win32":
        import winreg

        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, autostart_key)
        except FileNotFoundError:
            pass
    # Destroy this test's Qt objects here, on the main thread. Otherwise the
    # garbage collector may do it on a worker thread during a later test, which
    # corrupts Qt's state and crashes the process with an access violation.
    gc.collect()
    root = logging.getLogger()
    for handler in list(root.handlers):
        if not type(handler).__module__.startswith("_pytest"):
            root.removeHandler(handler)
            handler.close()
