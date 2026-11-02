"""Working out which open window a spoken name means, and where keys may go.

Pure logic, so the rules can be tested without real windows.

Names match the app's program name first, because a window's title can say
anything: a Chrome tab about Word shouldn't count as Word. If a name fits
windows of several different apps, Drivion asks instead of guessing, because
closing the wrong one could lose work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Typing here would mean running commands, which Drivion must never do.
COMMAND_PROGRAMS = {
    "cmd.exe", "powershell.exe", "pwsh.exe", "powershell_ise.exe", "windowsterminal.exe", "conhost.exe",
    "openconsole.exe", "wsl.exe", "wslhost.exe", "bash.exe", "mintty.exe", "regedit.exe",
    # Windows search can start any program by name.
    "searchhost.exe", "searchapp.exe", "startmenuexperiencehost.exe",
}
COMMAND_TITLES = {"run", "create new task"}


@dataclass(frozen=True)
class AppWindow:
    hwnd: int
    process: str
    title: str

    @property
    def app_name(self) -> str:
        """A name for replies: the title's last part ("Report - Word" -> "Word")."""
        title = self.title.rsplit(" - ", 1)[-1].strip()
        return title or self.process.removesuffix(".exe")


@dataclass(frozen=True)
class WindowSearch:
    """Exactly one of: ``windows`` found, several apps in ``options``, or nothing."""

    windows: tuple[AppWindow, ...] = ()
    options: tuple[str, ...] = ()


def _words(text: str) -> set[str]:
    return set(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


def find_windows(windows: list[AppWindow], spoken: str, process: str | None = None) -> WindowSearch:
    """``process``: the program name, when the app is in your allowlist."""
    if process is not None:
        return WindowSearch(tuple(w for w in windows if w.process.lower() == process.lower()))
    wanted = _words(spoken) - {"the", "my", "app", "window", "windows"}
    if not wanted:
        return WindowSearch()
    by_program = [w for w in windows if wanted <= _words(w.process.removesuffix(".exe"))]
    found = by_program or [w for w in windows if wanted <= _words(w.title)]
    programs = {w.process.lower() for w in found}
    if len(programs) > 1:
        return WindowSearch(options=tuple(sorted({w.app_name for w in found}))[:3])
    return WindowSearch(tuple(found))


def keyboard_refusal(window: AppWindow | None) -> str | None:
    """Why keys mustn't go to this window, or None if they may."""
    if window is None:
        return "I can't tell which window you're using, so I didn't press anything."
    if window.process.lower() in COMMAND_PROGRAMS or window.title.strip().lower() in COMMAND_TITLES:
        return "I don't type or press keys in command windows, for safety."
    return None
