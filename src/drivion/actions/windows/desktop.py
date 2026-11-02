"""Opening things, finding/minimizing app windows, and locking - via Win32.

* ``open_target`` uses ShellExecute (``os.startfile``): the string is treated
  as one file, folder or URL to open, never as a command line.
* Windows are found by the executable name of their process, so
  "minimize chrome" only touches chrome.exe's own windows.
* ``open_surface`` presses one fixed shortcut from ``HOTKEYS``, and Win+R is left
  out on purpose: it opens the Run box.
* ``close`` sends a normal close request (WM_CLOSE), so an app can still ask to
  save. Drivion never force-closes anything.
"""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes as wt
from pathlib import Path
from typing import Protocol

from drivion.actions.window_finder import AppWindow

SW_MAXIMIZE = 3
SW_MINIMIZE = 6
SW_RESTORE = 9
WM_CLOSE = 0x0010
DWMWA_CLOAKED = 14
INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
GW_OWNER = 4
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
# Shell windows that belong to explorer.exe but aren't "File Explorer windows".
APP_HOST = "applicationframehost.exe"
SNAP_ASSIST = "Snap Assist"
_SHELL_CLASSES = {"Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman", "WorkerW"}

VK_TAB = 0x09
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_LWIN = 0x5B
_EXTENDED_KEYS = {VK_LWIN, *range(0x21, 0x29)}  # Windows key, page keys, Home, End, arrows
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
HOTKEYS: dict[str, tuple[int, ...]] = {
    "start_menu": (VK_LWIN,),
    "search": (VK_LWIN, ord("S")),
    "desktop": (VK_LWIN, ord("D")),
    "notifications": (VK_LWIN, ord("N")),
    "quick_settings": (VK_LWIN, ord("A")),
    "task_view": (VK_LWIN, VK_TAB),
}


class Desktop(Protocol):
    def open_target(self, target: str) -> None: ...
    def open_surface(self, surface: str) -> None: ...
    def press(self, keys: tuple[int, ...]) -> None: ...
    def type_text(self, text: str) -> None: ...
    def list_windows(self) -> list[AppWindow]: ...
    def keyboard_target(self) -> AppWindow | None: ...
    def focus(self, hwnd: int) -> bool: ...
    def snap(self, hwnd: int, left: bool) -> bool: ...
    def maximize(self, hwnd: int) -> None: ...
    def close(self, hwnd: int) -> None: ...
    def is_open(self, hwnd: int) -> bool: ...
    def lock(self) -> bool: ...
    def app_windows(self, process: str) -> list[int]: ...
    def minimize(self, hwnd: int) -> None: ...
    def restore(self, hwnd: int) -> None: ...
    def is_minimized(self, hwnd: int) -> bool: ...


class _KeyboardInput(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _MouseInput(ctypes.Structure):  # only here because it sets the union's size
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _InputUnion(ctypes.Union):
    _fields_ = [("ki", _KeyboardInput), ("mi", _MouseInput)]


class _Input(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _InputUnion)]


def _user32():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetWindow.argtypes = [wt.HWND, wt.UINT]
    user32.GetWindow.restype = wt.HWND
    for name in ("IsWindowVisible", "IsIconic", "GetWindowTextLengthW", "SetForegroundWindow"):
        getattr(user32, name).argtypes = [wt.HWND]
    user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.IsWindow.argtypes = [wt.HWND]
    user32.GetForegroundWindow.restype = wt.HWND
    return user32


def _is_cloaked(hwnd: int) -> bool:
    """Suspended modern apps keep a window that's "visible" but not really there."""
    cloaked = wt.DWORD()
    ctypes.windll.dwmapi.DwmGetWindowAttribute(wt.HWND(hwnd), DWMWA_CLOAKED, ctypes.byref(cloaked),
                                               ctypes.sizeof(cloaked))
    return bool(cloaked.value)


def _hosted_process(user32, hwnd: int, host_pid: int) -> str | None:
    """Modern apps such as Calculator draw inside a shared host's window, so the real
    program is the owner of its child window. A minimized app can briefly have none."""
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def visit(child, _lparam):
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(child, ctypes.byref(pid))
        if pid.value != host_pid:
            found.append(pid.value)
            return False
        return True

    user32.EnumChildWindows(hwnd, visit, 0)
    return _process_name(found[0]) if found else None


def _describe(user32, hwnd: int, names: dict[int, str | None] | None = None) -> AppWindow | None:
    """A window as an ``AppWindow``, or None for shell windows and Drivion's own."""
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == os.getpid():
        return None
    names = {} if names is None else names
    if pid.value not in names:
        names[pid.value] = _process_name(pid.value)
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    if not names[pid.value] or cls.value in _SHELL_CLASSES:
        return None
    title = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title, 512)
    if title.value == SNAP_ASSIST:  # the overlay after snapping, not a window you're using
        return None
    process = names[pid.value]
    if process.lower() == APP_HOST:
        process = _hosted_process(user32, hwnd, pid.value) or process
    return AppWindow(int(hwnd), process, title.value)


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

    def open_surface(self, surface: str) -> None:
        self.press(HOTKEYS[surface])

    def press(self, keys: tuple[int, ...]) -> None:
        user32 = ctypes.windll.user32

        def send(key: int, flags: int = 0) -> None:
            extended = KEYEVENTF_EXTENDEDKEY if key in _EXTENDED_KEYS else 0
            user32.keybd_event(key, 0, flags | extended, 0)

        for key in keys:
            send(key)
        for key in reversed(keys):  # always released, so no key is left held down
            send(key, KEYEVENTF_KEYUP)

    def type_text(self, text: str) -> None:
        units = text.encode("utf-16-le")
        events = (_Input * len(units))()  # two per character: key down, key up
        for index in range(0, len(units), 2):
            unit = int.from_bytes(units[index:index + 2], "little")
            for offset, flags in ((0, KEYEVENTF_UNICODE), (1, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)):
                event = events[index + offset]
                event.type = INPUT_KEYBOARD
                event.u.ki = _KeyboardInput(0, unit, flags, 0, 0)
        if ctypes.windll.user32.SendInput(len(events), events, ctypes.sizeof(_Input)) != len(events):
            raise OSError("Windows blocked the keystrokes")

    def list_windows(self) -> list[AppWindow]:
        """Open app windows, most recently used first, without Drivion's own."""
        user32 = _user32()
        found: list[AppWindow] = []
        names: dict[int, str | None] = {}

        @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        def visit(hwnd, _lparam):
            if (user32.IsWindowVisible(hwnd) and not user32.GetWindow(hwnd, GW_OWNER)
                    and user32.GetWindowTextLengthW(hwnd) > 0 and not _is_cloaked(hwnd)):
                window = _describe(user32, hwnd, names)
                if window is not None:
                    found.append(window)
            return True

        user32.EnumWindows(visit, 0)
        return found

    def keyboard_target(self) -> AppWindow | None:
        """The window keys would reach. Drivion's own window moves aside for the last app used."""
        user32 = _user32()
        foreground = user32.GetForegroundWindow()
        window = _describe(user32, foreground) if foreground else None
        if window is not None:
            return window
        windows = self.list_windows()
        if not windows or not self.focus(windows[0].hwnd):
            return None
        return windows[0]

    def focus(self, hwnd: int) -> bool:
        """Bring a window forward. False if Windows refused, so keys go nowhere unintended."""
        user32 = _user32()
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if user32.GetForegroundWindow() == hwnd:
                return True
            time.sleep(0.02)
        return False

    def snap(self, hwnd: int, left: bool) -> bool:
        if not self.focus(hwnd):
            return False
        self.press((VK_LWIN, VK_LEFT if left else VK_RIGHT))
        return True

    def maximize(self, hwnd: int) -> None:
        _user32().ShowWindow(hwnd, SW_MAXIMIZE)

    def close(self, hwnd: int) -> None:
        _user32().PostMessageW(hwnd, WM_CLOSE, 0, 0)

    def is_open(self, hwnd: int) -> bool:
        return bool(_user32().IsWindow(hwnd))

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
