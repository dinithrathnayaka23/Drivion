"""Application states and the rules for moving between them.

This module is pure Python (no Qt) so the rules can be tested in isolation.
The ``StateMachine`` only answers "is this move legal?" and records the move;
*deciding* which move to make in response to an event is the controller's job.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

log = logging.getLogger(__name__)


class AppState(StrEnum):
    STANDBY = "STANDBY"              # UI hidden; only the wake-word listener runs
    VERIFYING = "VERIFYING"          # checking the user's face
    ACTIVE = "ACTIVE"                # dashboard open, commands accepted
    SLEEPING = "SLEEPING"            # tearing active services down, then STANDBY
    ERROR = "ERROR"                  # a subsystem failed; waiting for recovery
    SHUTTING_DOWN = "SHUTTING_DOWN"  # releasing everything; the process will exit


_S = AppState
ALLOWED_TRANSITIONS: dict[AppState, frozenset[AppState]] = {
    _S.STANDBY: frozenset({_S.VERIFYING, _S.ERROR, _S.SHUTTING_DOWN}),
    _S.VERIFYING: frozenset({_S.ACTIVE, _S.STANDBY, _S.ERROR, _S.SHUTTING_DOWN}),
    _S.ACTIVE: frozenset({_S.SLEEPING, _S.ERROR, _S.SHUTTING_DOWN}),
    _S.SLEEPING: frozenset({_S.STANDBY, _S.ERROR, _S.SHUTTING_DOWN}),
    _S.ERROR: frozenset({_S.STANDBY, _S.SHUTTING_DOWN}),
    _S.SHUTTING_DOWN: frozenset(),  # terminal: nothing comes after shutdown
}


class InvalidTransitionError(Exception):
    def __init__(self, current: AppState, target: AppState) -> None:
        super().__init__(f"Transition {current} -> {target} is not allowed")
        self.current = current
        self.target = target


@dataclass(frozen=True)
class Transition:
    old: AppState
    new: AppState
    reason: str
    timestamp: float = field(default_factory=time.time)


TransitionListener = Callable[[Transition], None]


class StateMachine:
    def __init__(self, initial: AppState = AppState.STANDBY) -> None:
        self._state = initial
        self._lock = threading.Lock()
        self._listeners: list[TransitionListener] = []

    @property
    def state(self) -> AppState:
        return self._state

    def can_transition(self, target: AppState) -> bool:
        return target in ALLOWED_TRANSITIONS[self._state]

    def add_listener(self, listener: TransitionListener) -> None:
        self._listeners.append(listener)

    def transition(self, target: AppState, reason: str = "") -> Transition:
        """Move to ``target`` or raise ``InvalidTransitionError``.

        The check and the update happen under one lock, so two threads can
        never both "win" a transition out of the same state.
        """
        with self._lock:
            if target not in ALLOWED_TRANSITIONS[self._state]:
                raise InvalidTransitionError(self._state, target)
            record = Transition(self._state, target, reason)
            self._state = target

        log.info("State %s -> %s (%s)", record.old, record.new, reason or "no reason given")
        # Listeners run outside the lock so a slow or re-entrant listener
        # can't deadlock the state machine.
        for listener in list(self._listeners):
            try:
                listener(record)
            except Exception:
                log.exception("State listener %r failed", listener)
        return record
