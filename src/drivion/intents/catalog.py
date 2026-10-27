"""The allowlist of things Drivion may open: apps, websites and folders.

Spoken names ("google chrome", "browser") are resolved to an id ("chrome")
that comes from your config. Anything not in the list can't be opened,
which keeps "open <anything>" from becoming "run <anything>".

Milestone 6 only resolves names; Milestone 7 adds how each app is
actually launched.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from drivion.intents.normalize import normalize

# Words people wrap around a target name: "open *the* downloads *folder*".
_TARGET_PREFIXES = ("the ", "my ", "a ", "an ", "up ")
_TARGET_SUFFIXES = (
    " folder", " directory", " website", " web site", " site", " page", " app",
    " application", " program", " window", " browser window",
)


class TargetKind(StrEnum):
    APP = "APP"
    WEBSITE = "WEBSITE"
    FOLDER = "FOLDER"


@dataclass(frozen=True)
class Target:
    kind: TargetKind
    id: str


class Catalog:
    def __init__(
        self,
        apps: dict[str, list[str]],
        websites: dict[str, str],
        folders: dict[str, str],
    ) -> None:
        self.apps, self.websites, self.folders = apps, websites, folders
        self._aliases: dict[str, Target] = {}
        for app_id, aliases in apps.items():
            for alias in [app_id.replace("_", " "), *aliases]:
                self._add(alias, Target(TargetKind.APP, app_id))
        for site in websites:
            self._add(site.replace("_", " "), Target(TargetKind.WEBSITE, site))
        for folder in folders:
            self._add(folder.replace("_", " "), Target(TargetKind.FOLDER, folder))

    @classmethod
    def from_settings(cls, commands) -> "Catalog":
        """Build from ``CommandsSettings`` (the [commands] config section)."""
        return cls(commands.app_aliases, commands.websites, commands.folders)

    def spoken_name(self, target_id: str) -> str:
        """How to say an id in a reply: "vscode" -> "vs code" (its first alias)."""
        aliases = self.apps.get(target_id)
        return aliases[0] if aliases else target_id.replace("_", " ")

    def _add(self, alias: str, target: Target) -> None:
        key = normalize(alias)
        existing = self._aliases.get(key)
        if existing is not None and existing != target:
            raise ValueError(f"{alias!r} refers to both {existing.id!r} and {target.id!r}")
        self._aliases[key] = target

    def resolve(self, spoken: str) -> Target | None:
        name = spoken.strip()
        changed = True
        while changed:  # peel "the", "my", "folder", ... in any combination
            changed = False
            if name in self._aliases:
                return self._aliases[name]
            for prefix in _TARGET_PREFIXES:
                if name.startswith(prefix):
                    name, changed = name[len(prefix):], True
            for suffix in _TARGET_SUFFIXES:
                if name.endswith(suffix):
                    name, changed = name[: -len(suffix)], True
        return self._aliases.get(name)

