"""Screen brightness via WMI (built-in laptop panels).

External monitors usually don't support WMI brightness; then
``BrightnessUnsupported`` is raised and Drivion says so instead of
pretending. PowerShell is run with a fixed script: the only variable part
is an integer that has already been validated to be 0..100.
"""

from __future__ import annotations

import subprocess
from typing import Protocol

CREATE_NO_WINDOW = 0x08000000

_GET = ("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness "
        "-ErrorAction Stop | Select-Object -First 1).CurrentBrightness")
_SET = ("$m = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods "
        "-ErrorAction Stop | Select-Object -First 1; "
        "Invoke-CimMethod -InputObject $m -MethodName WmiSetBrightness "
        "-Arguments @{{Timeout=1; Brightness=[byte]{level}}} -ErrorAction Stop | Out-Null")


class BrightnessUnsupported(Exception):
    pass


class BrightnessControl(Protocol):
    def get_percent(self) -> int: ...
    def set_percent(self, percent: int) -> None: ...


def _powershell(script: str, timeout_s: float = 10.0) -> str:
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=timeout_s, creationflags=CREATE_NO_WINDOW,
    )
    if completed.returncode != 0:
        raise BrightnessUnsupported(completed.stderr.strip()[:200] or "WMI brightness failed")
    return completed.stdout.strip()


class WmiBrightness:
    def get_percent(self) -> int:
        out = _powershell(_GET)
        if not out:
            raise BrightnessUnsupported("this screen doesn't report its brightness")
        try:
            return int(out)
        except ValueError as exc:
            raise BrightnessUnsupported(f"unexpected reply {out!r}") from exc

    def set_percent(self, percent: int) -> None:
        level = max(0, min(100, int(percent)))  # int() again: nothing but digits reach the script
        _powershell(_SET.format(level=level))
