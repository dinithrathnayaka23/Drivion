"""Sleep, restart and shut down - the only destructive actions.

Safety layers around this module:
1. The intents are HIGH risk, so ``SafeExecutor`` requires a spoken "yes".
2. Restart/shutdown use ``shutdown.exe`` with a delay, so "cancel" can still
   abort them (``shutdown /a``).
3. If ``DRIVION_POWER_DRY_RUN`` is set (the test suite always sets it),
   every method refuses to run, so a test can never power anything off by
   accident - even if it forgot to use a fake.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
from typing import Protocol

CREATE_NO_WINDOW = 0x08000000
ERROR_NO_SHUTDOWN_IN_PROGRESS = 1116
DRY_RUN_ENV = "DRIVION_POWER_DRY_RUN"


class PowerBlocked(RuntimeError):
    """Raised instead of touching power state when dry-run is on."""


class PowerControl(Protocol):
    def sleep(self, hibernate: bool) -> None: ...
    def schedule_restart(self, delay_s: int) -> None: ...
    def schedule_shutdown(self, delay_s: int) -> None: ...
    def abort_scheduled(self) -> bool: ...


def _guard(action: str) -> None:
    if os.environ.get(DRY_RUN_ENV):
        raise PowerBlocked(f"{action} blocked: {DRY_RUN_ENV} is set")


def _shutdown_exe(*args: str) -> subprocess.CompletedProcess:
    # Fixed program and fixed arguments; the only variable is an int delay.
    return subprocess.run(["shutdown.exe", *args], capture_output=True, text=True,
                          timeout=15, creationflags=CREATE_NO_WINDOW)


class WindowsPower:
    def sleep(self, hibernate: bool) -> None:
        _guard("sleep")
        powrprof = ctypes.WinDLL("powrprof", use_last_error=True)
        powrprof.SetSuspendState.argtypes = [ctypes.c_bool, ctypes.c_bool, ctypes.c_bool]
        if not powrprof.SetSuspendState(hibernate, False, False):
            # Common on Modern Standby laptops: ERROR_NOT_SUPPORTED for sleep.
            raise ctypes.WinError(ctypes.get_last_error())

    def schedule_restart(self, delay_s: int) -> None:
        _guard("restart")
        self._schedule("/r", int(delay_s), "Drivion is restarting the computer")

    def schedule_shutdown(self, delay_s: int) -> None:
        _guard("shutdown")
        self._schedule("/s", int(delay_s), "Drivion is shutting down the computer")

    def abort_scheduled(self) -> bool:
        _guard("abort")
        completed = _shutdown_exe("/a")
        if completed.returncode == ERROR_NO_SHUTDOWN_IN_PROGRESS:
            return False
        if completed.returncode != 0:
            raise OSError(completed.stderr.strip() or f"shutdown /a failed ({completed.returncode})")
        return True

    @staticmethod
    def _schedule(flag: str, delay_s: int, comment: str) -> None:
        completed = _shutdown_exe(flag, "/t", str(delay_s), "/c", comment)
        if completed.returncode != 0:
            raise OSError(completed.stderr.strip() or f"shutdown {flag} failed ({completed.returncode})")
