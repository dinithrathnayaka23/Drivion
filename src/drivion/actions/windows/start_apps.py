"""The Start menu's list of apps, as Windows reports it.

The script is fixed text with nothing from a command in it. Apps are later
opened by id through ``shell:AppsFolder``, which ShellExecute treats as one
item to open, never as a command line.
"""

from __future__ import annotations

import json
import subprocess

CREATE_NO_WINDOW = 0x08000000
_LIST = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
         "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress")


def list_start_apps(timeout_s: float = 15.0) -> list[tuple[str, str]]:
    """(name, app id) for everything in the Start menu. Raises if Windows can't say."""
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _LIST],
        capture_output=True, encoding="utf-8", errors="replace", timeout=timeout_s,
        creationflags=CREATE_NO_WINDOW, check=True,
    )
    entries = json.loads(completed.stdout or "[]")
    if isinstance(entries, dict):  # PowerShell writes a single result without the list
        entries = [entries]
    return [(entry["Name"], entry["AppID"]) for entry in entries if entry.get("Name") and entry.get("AppID")]


def apps_folder_target(app_id: str) -> str:
    return f"shell:AppsFolder\\{app_id}"
