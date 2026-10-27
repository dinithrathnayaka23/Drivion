"""The only place where actions are executed, and the rules around it.

Rules, in order:

1. **Registered only.** An intent without an ``ActionSpec`` is refused.
2. **Authorized only (fail closed).** Every run - and every confirmation -
   checks ``is_authorized()`` (Drivion must be ACTIVE, i.e. verified). If
   that can't be confirmed, nothing runs.
3. **High risk needs a "yes".** Sleep, restart and shut down are held as a
   *pending* action and only run on an explicit Confirm within
   ``confirmation_timeout_s``. "No", "cancel", a timeout or any other
   command drops it.
4. **Handlers can't crash Drivion.** An exception becomes a failed result.

Every decision is written to the log as an audit trail.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from drivion.actions.registry import ActionRegistry, ActionResult, ActionSpec
from drivion.intents import schemas as s

log = logging.getLogger("drivion.audit")

NOT_ALLOWED = "I can't do that right now: Drivion isn't unlocked."


@dataclass(frozen=True)
class Done:
    result: ActionResult


@dataclass(frozen=True)
class NeedsConfirmation:
    prompt: str


@dataclass(frozen=True)
class Refused:
    reason: str


Decision = Done | NeedsConfirmation | Refused


@dataclass
class _Pending:
    spec: ActionSpec
    intent: s._Intent
    expires_at: float


class SafeExecutor:
    def __init__(
        self,
        registry: ActionRegistry,
        is_authorized: Callable[[], bool],
        confirmation_timeout_s: float = 15.0,
        describe: Callable[[s._Intent], str] = s.describe,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._registry = registry
        self._is_authorized = is_authorized
        self._timeout = confirmation_timeout_s
        self._describe = describe
        self._clock = clock
        self._pending: _Pending | None = None
        self._lock = threading.RLock()  # one action at a time

    def handles(self, intent: s._Intent) -> bool:
        return intent.kind in self._registry

    @property
    def has_pending(self) -> bool:
        with self._lock:
            return self._pending is not None and self._clock() < self._pending.expires_at

    def request(self, intent: s._Intent) -> Decision:
        with self._lock:
            spec = self._registry.get(intent.kind)
            if spec is None:
                log.warning("REFUSED %s: not a registered action", intent.kind)
                return Refused("That isn't something I'm allowed to do.")
            if not self._authorized(spec):
                return Refused(NOT_ALLOWED)
            if spec.needs_confirmation:
                self._pending = _Pending(spec, intent, self._clock() + self._timeout)
                what = self._describe(intent)
                log.info("PENDING %s (risk %s): waiting for confirmation", spec.kind, spec.risk)
                return NeedsConfirmation(f"Are you sure you want me to {what}? Say yes or no.")
            return Done(self._run(spec, intent))

    def confirm(self) -> Decision | None:
        """Run the pending action. None if nothing is pending (or it expired)."""
        with self._lock:
            pending = self._take_pending()
            if pending is None:
                return None
            if not self._authorized(pending.spec):  # state may have changed while waiting
                return Refused(NOT_ALLOWED)
            log.info("CONFIRMED %s", pending.spec.kind)
            return Done(self._run(pending.spec, pending.intent))

    def drop_pending(self, reason: str) -> s._Intent | None:
        """Forget the pending action; returns it if there was one."""
        with self._lock:
            pending = self._take_pending()
            if pending is not None:
                log.info("DROPPED %s: %s", pending.spec.kind, reason)
                return pending.intent
            return None

    # ----- internals ----------------------------------------------------------------

    def _take_pending(self) -> _Pending | None:
        pending, self._pending = self._pending, None
        if pending is not None and self._clock() >= pending.expires_at:
            log.info("EXPIRED %s: no confirmation in %.0fs", pending.spec.kind, self._timeout)
            return None
        return pending

    def _authorized(self, spec: ActionSpec) -> bool:
        try:
            allowed = bool(self._is_authorized())
        except Exception:
            log.exception("Authorization check failed")
            allowed = False  # fail closed
        if not allowed:
            log.warning("REFUSED %s: not authorized", spec.kind)
        return allowed

    def _run(self, spec: ActionSpec, intent: s._Intent) -> ActionResult:
        started = time.perf_counter()
        try:
            result = spec.handler(intent)
        except Exception:
            log.exception("FAILED %s: handler raised", spec.kind)
            result = ActionResult(False, f"Sorry, I couldn't {self._describe(intent)}.")
        log.info("%s %s %s (risk %s, %s, %.0f ms): %s",
                 "DONE" if result.success else "FAILED", spec.kind,
                 intent.model_dump_json(exclude={"kind"}), spec.risk,
                 "verified" if result.verified else "not verified",
                 1000 * (time.perf_counter() - started), result.message)
        return result
