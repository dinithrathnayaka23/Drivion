"""The central list of everything Drivion is allowed to do to the computer.

Each ``ActionSpec`` ties an intent kind (``SET_VOLUME``) to:

* a human description and a **risk level**,
* whether it needs **spoken confirmation** before running,
* the **handler** that performs it and reports a verified ``ActionResult``.

If an intent has no entry here, it can't be executed - there is no
fallback to "run something". The ``SafeExecutor`` (``safety/executor.py``)
is the only code that calls handlers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from drivion.intents import schemas as s


class Risk(StrEnum):
    LOW = "LOW"        # easily undone: volume, brightness, opening an allowlisted app
    MEDIUM = "MEDIUM"  # disruptive but harmless: locking the computer
    HIGH = "HIGH"      # can lose unsaved work: sleep, restart, shut down


@dataclass(frozen=True)
class ActionResult:
    success: bool
    message: str          # what Drivion says
    verified: bool = False  # True when the effect was checked, not just requested


Handler = Callable[[s._Intent], ActionResult]


@dataclass(frozen=True)
class ActionSpec:
    kind: str
    description: str
    risk: Risk
    handler: Handler

    @property
    def needs_confirmation(self) -> bool:
        return self.risk is Risk.HIGH


class ActionRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ActionSpec] = {}

    def register(self, kind: str, description: str, risk: Risk, handler: Handler) -> None:
        if kind not in s.INTENT_TYPES:
            raise ValueError(f"{kind!r} is not a known intent")
        if kind in self._specs:
            raise ValueError(f"{kind!r} is already registered")
        self._specs[kind] = ActionSpec(kind, description, risk, handler)

    def get(self, kind: str) -> ActionSpec | None:
        return self._specs.get(kind)

    def __contains__(self, kind: str) -> bool:
        return kind in self._specs

    @property
    def specs(self) -> list[ActionSpec]:
        return list(self._specs.values())
