"""Dark and light mode: two per-user registry values, then a notice to open apps."""

from __future__ import annotations

import ctypes
from typing import Protocol

_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
_VALUES = ("AppsUseLightTheme", "SystemUsesLightTheme")
HWND_BROADCAST = 0xFFFF
WM_SETTINGCHANGE = 0x001A
SMTO_ABORTIFHUNG = 0x0002


class ThemeControl(Protocol):
    def is_dark(self) -> bool: ...
    def set_dark(self, dark: bool) -> None: ...


class WindowsTheme:
    def is_dark(self) -> bool:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY) as key:
            return winreg.QueryValueEx(key, _VALUES[0])[0] == 0

    def set_dark(self, dark: bool) -> None:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY, 0, winreg.KEY_SET_VALUE) as key:
            for name in _VALUES:
                winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, 0 if dark else 1)
        result = ctypes.c_size_t()
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, ctypes.c_wchar_p("ImmersiveColorSet"),
            SMTO_ABORTIFHUNG, 1000, ctypes.byref(result),
        )
