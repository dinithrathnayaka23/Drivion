"""Opening things, finding/minimizing app windows, and locking - via Win32.

* ``open_target`` uses ShellExecute (``os.startfile``): the string is treated
  as one file, folder or URL to open, never as a command line.
* Windows are found by the executable name of their process, so
  "minimize chrome" only touches chrome.exe's own windows.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes as wt
from pathlib import Path
from typing import Protocol

SW_MINIMIZE = 6
SW_RESTORE = 9
GW_OWNER = 4
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
# Shell windows that belong to explorer.exe but aren't "File Explorer windows".
_SHELL_CLASSES = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW"}


class Desktop(Protocol):
    def open_target(self, target: str) -> None: ...
    def lock(self) -> bool: ...
    def app_windows(self, process: str) -> list[int]: ...
    def minimize(self, hwnd: int) -> None: ...
    def restore(self, hwnd: int) -> None: ...
    def is_minimized(self, hwnd: int) -> bool: ...


def _user32():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetWindow.argtypes = [wt.HWND, wt.UINT]
    user32.GetWindow.restype = wt.HWND
    for name in ("IsWindowVisible", "IsIconic", "GetWindowTextLengthW", "SetForegroundWindow"):
        getattr(user32, name).argtypes = [wt.HWND]
    user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    return user32


def _process_name(pid: int) -> str | None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR,
                                                    ctypes.POINTER(wt.DWORD)]
    kernel32.CloseHandle.argtypes = [wt.HANDLE]
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wt.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return Path(buffer.value).name
    finally:
        kernel32.CloseHandle(handle)


class WindowsDesktop:
    def open_target(self, target: str) -> None:
        os.startfile(target)  # raises OSError if Windows can't open it

    def lock(self) -> bool:
        return bool(ctypes.windll.user32.LockWorkStation())

    def app_windows(self, process: str) -> list[int]:
        user32 = _user32()
        wanted = process.lower()
        found: list[int] = []
        names: dict[int, str | None] = {}

        @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        def visit(hwnd, _lparam):
            if (user32.IsWindowVisible(hwnd) and not user32.GetWindow(hwnd, GW_OWNER)
                    and user32.GetWindowTextLengthW(hwnd) > 0):
                pid = wt.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value not in names:
                    names[pid.value] = _process_name(pid.value)
                name = names[pid.value]
                if name and name.lower() == wanted:
                    cls = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(hwnd, cls, 256)
                    if cls.value not in _SHELL_CLASSES:
                        found.append(hwnd)
            return True

        user32.EnumWindows(visit, 0)
        return found

    def minimize(self, hwnd: int) -> None:
        _user32().ShowWindow(hwnd, SW_MINIMIZE)

    def restore(self, hwnd: int) -> None:
        user32 = _user32()
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)  # Windows may refuse; restoring still worked

    def is_minimized(self, hwnd: int) -> bool:
        return bool(_user32().IsIconic(hwnd))
