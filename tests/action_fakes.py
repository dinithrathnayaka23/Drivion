"""In-memory stand-ins for every Windows action backend. Nothing touches the system."""

from __future__ import annotations

from pathlib import Path

from drivion.actions.handlers import Backends
from drivion.actions.windows.display import BrightnessUnsupported


class FakeVolume:
    def __init__(self, percent=40, muted=False, sticky=False):
        self.percent, self.muted, self.sticky = percent, muted, sticky

    def get_percent(self):
        return self.percent

    def set_percent(self, percent):
        if not self.sticky:  # sticky = the device ignores changes (to test verification)
            self.percent = percent

    def is_muted(self):
        return self.muted

    def set_muted(self, muted):
        if not self.sticky:
            self.muted = muted


class FakeBrightness:
    def __init__(self, percent=50, supported=True):
        self.percent, self.supported, self.sets = percent, supported, []

    def get_percent(self):
        if not self.supported:
            raise BrightnessUnsupported("external monitor")
        return self.percent

    def set_percent(self, percent):
        if not self.supported:
            raise BrightnessUnsupported("external monitor")
        self.sets.append(percent)
        self.percent = percent


class FakeDesktop:
    def __init__(self, windows=None, openable=None, lock_ok=True):
        self.windows = windows or {}          # process -> {hwnd: minimized?}
        self.openable = openable              # None = everything opens
        self.opened, self.locked = [], 0
        self.lock_ok = lock_ok
        self.starts_window = {}               # launch target -> process to "start"

    def open_target(self, target):
        if self.openable is not None and target not in self.openable:
            raise OSError("not found")
        self.opened.append(target)
        if target in self.starts_window:
            self.windows.setdefault(self.starts_window[target], {})[999] = False

    def lock(self):
        self.locked += 1
        return self.lock_ok

    def app_windows(self, process):
        return list(self.windows.get(process, {}))

    def _find(self, hwnd):
        for wins in self.windows.values():
            if hwnd in wins:
                return wins
        raise KeyError(hwnd)

    def minimize(self, hwnd):
        self._find(hwnd)[hwnd] = True

    def restore(self, hwnd):
        self._find(hwnd)[hwnd] = False

    def is_minimized(self, hwnd):
        return self._find(hwnd)[hwnd]


class FakeScreen:
    def __init__(self, fail=False):
        self.fail, self.paths = fail, []

    def capture(self, path: Path):
        if self.fail:
            raise OSError("no screen")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG fake")
        self.paths.append(path)
        return 1280, 720


class FakePower:
    """Records power requests. The real WindowsPower is never used in tests."""

    def __init__(self, refuse_sleep=False, abort_result=True):
        self.calls = []
        self.refuse_sleep, self.abort_result = refuse_sleep, abort_result

    def sleep(self, hibernate):
        self.calls.append(("sleep", hibernate))
        if self.refuse_sleep:
            raise OSError("ERROR_NOT_SUPPORTED")

    def schedule_restart(self, delay_s):
        self.calls.append(("restart", delay_s))

    def schedule_shutdown(self, delay_s):
        self.calls.append(("shutdown", delay_s))

    def abort_scheduled(self):
        self.calls.append(("abort",))
        return self.abort_result


def fake_backends(**overrides) -> Backends:
    parts = dict(volume=FakeVolume(), brightness=FakeBrightness(), desktop=FakeDesktop(),
                 screen=FakeScreen(), power=FakePower())
    parts.update(overrides)
    return Backends(**parts)
