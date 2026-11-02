"""Start Drivion when you sign in to Windows.

Uses the per-user "Run" key in the registry: no administrator rights, and it
shows up in Task Manager's Startup apps, where it can be turned off. It is off
until you turn it on, because Drivion listens for the wake word from sign-in.

``DRIVION_AUTOSTART_KEY`` replaces the key; the tests use it to stay away from
the real one.
"""

from __future__ import annotations

import os
import subprocess

from drivion.config import paths

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Drivion"


class Autostart:
    def __init__(self, key_path: str | None = None) -> None:
        self._key_path = key_path or os.environ.get("DRIVION_AUTOSTART_KEY") or RUN_KEY

    @staticmethod
    def command() -> str:
        """The text Windows runs at sign-in, quoted so spaces in the path are safe."""
        return subprocess.list2cmdline(paths.launch_command())

    def registered(self) -> str | None:
        """The command stored in the registry, or None when start at login is off."""
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._key_path) as key:
                return winreg.QueryValueEx(key, VALUE_NAME)[0]
        except FileNotFoundError:
            return None

    def is_enabled(self) -> bool:
        return self.registered() is not None

    def is_current(self) -> bool:
        """False when the entry points somewhere else, e.g. Drivion was moved."""
        return self.registered() == self.command()

    def enable(self) -> None:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self._key_path) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, self.command())

    def disable(self) -> None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._key_path, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass  # already off
