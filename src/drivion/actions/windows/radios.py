"""Turning Bluetooth and Wi-Fi on and off with the Windows radio API.

The API belongs to modern Windows apps, and Windows PowerShell can reach it
without adding a dependency. The script is fixed text: the radio and the
state come from fixed values, passed through the environment.
"""

from __future__ import annotations

import os
import subprocess
from typing import Protocol

CREATE_NO_WINDOW = 0x08000000
_KINDS = {"bluetooth": "Bluetooth", "wifi": "WiFi"}

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
function Await($operation, $type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($operation))
    $task.Wait(-1) | Out-Null
    $task.Result
}
[Windows.Devices.Radios.Radio, Windows.System.Devices, ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioAccessStatus, Windows.System.Devices, ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioState, Windows.System.Devices, ContentType=WindowsRuntime] | Out-Null
$access = Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus])
$listType = [System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]]
$radio = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) $listType |
    Where-Object { $_.Kind -eq $env:DRIVION_RADIO } | Select-Object -First 1
if (-not $radio) { Write-Output 'None'; exit 0 }
if ($env:DRIVION_RADIO_STATE) {
    Await ($radio.SetStateAsync($env:DRIVION_RADIO_STATE)) ([Windows.Devices.Radios.RadioAccessStatus]) | Out-Null
}
Write-Output $radio.State
"""


class RadioUnavailable(Exception):
    """This computer has no such radio, or Windows refused."""


class RadioControl(Protocol):
    def is_on(self, radio: str) -> bool: ...
    def set_on(self, radio: str, on: bool) -> None: ...


def _run(radio: str, state: str) -> str:
    env = {**os.environ, "DRIVION_RADIO": _KINDS[radio], "DRIVION_RADIO_STATE": state}
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _SCRIPT],
            capture_output=True, text=True, timeout=20, env=env, creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise RadioUnavailable("Windows didn't answer") from exc
    result = completed.stdout.strip().splitlines()
    if completed.returncode != 0 or not result:
        raise RadioUnavailable(completed.stderr.strip()[:200] or "radio request failed")
    if result[-1] == "None":
        raise RadioUnavailable(f"no {radio} radio")
    return result[-1]


class WindowsRadios:
    def is_on(self, radio: str) -> bool:
        return _run(radio, "") == "On"

    def set_on(self, radio: str, on: bool) -> None:
        _run(radio, "On" if on else "Off")
