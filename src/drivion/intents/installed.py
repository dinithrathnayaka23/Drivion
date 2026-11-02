"""Finding the apps installed on this computer by their spoken name.

The list comes from Windows (the Start menu), so "open <anything>" can still
only open something already listed there. Entries that change the system or
aren't apps are left out. Names are never guessed from similar spelling:
every spoken word must be a whole word of the name, and if that fits several
apps, Drivion asks instead of choosing. Opening the wrong app is worse than
asking.

Only your own spoken command can reach this. The AI's actions can't.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from drivion.intents.normalize import normalize

log = logging.getLogger(__name__)

MAX_AGE_S = 300.0  # so a newly installed app shows up without a restart
MAX_OPTIONS = 3

# Whole words in a name that mean it changes the system rather than being an app.
_SYSTEM_CHANGING = {"uninstall", "uninstaller", "remove", "repair", "reset", "setup",
                    "installer", "administrator", "admin"}
_NOT_APPS = re.compile(r"^(?:[a-z][a-z0-9+.-]+://|.*\.(?:url|chm|pdf|txt|html?|rtf|docx?)$)", re.IGNORECASE)
_FILLER = ("the ", "my ", "a ", "an ")
_SUFFIXES = (" app", " application", " program")

Lister = Callable[[], list[tuple[str, str]]]


def _words(name: str) -> str:
    return normalize(name.replace("+", " plus "))


def is_openable(name: str, app_id: str) -> bool:
    return not (_NOT_APPS.match(app_id) or _SYSTEM_CHANGING & set(_words(name).split()))


@dataclass(frozen=True)
class AppSearch:
    """Exactly one of: ``name`` found, several ``options``, or nothing."""

    name: str | None = None
    options: tuple[str, ...] = ()


class InstalledApps:
    def __init__(self, lister: Lister, max_age_s: float = MAX_AGE_S,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._lister = lister
        self._max_age_s = max_age_s
        self._clock = clock
        self._lock = threading.Lock()
        self._apps: dict[str, tuple[str, str]] = {}  # spoken form -> (name, app id)
        self._loaded_at: float | None = None

    def _current(self) -> dict[str, tuple[str, str]]:
        with self._lock:
            if self._loaded_at is None or self._clock() - self._loaded_at >= self._max_age_s:
                try:
                    entries = self._lister()
                except Exception as exc:  # keep the last good list; a stale list beats none
                    log.warning("Couldn't list installed apps: %s", exc)
                    return self._apps
                apps: dict[str, tuple[str, str]] = {}
                for name, app_id in entries:
                    if is_openable(name, app_id):
                        apps.setdefault(_words(name), (name, app_id))
                self._apps, self._loaded_at = apps, self._clock()
            return self._apps

    def __len__(self) -> int:
        return len(self._current())

    def app_id(self, name: str) -> str | None:
        """The Windows id of an app from ``find``, checked against the list again."""
        found = self._current().get(_words(name))
        return found[1] if found else None

    def find(self, spoken: str) -> AppSearch:
        apps = self._current()
        wanted = _words(spoken)
        for prefix in _FILLER:
            wanted = wanted.removeprefix(prefix)
        for suffix in _SUFFIXES:
            wanted = wanted.removesuffix(suffix)
        if wanted in apps:
            return AppSearch(apps[wanted][0])
        words = set(wanted.split())
        if not words:
            return AppSearch()
        matches = sorted(name for key, (name, _) in apps.items() if words <= set(key.split()))
        if len(matches) == 1:
            return AppSearch(matches[0])
        return AppSearch(options=tuple(matches[:MAX_OPTIONS]))
