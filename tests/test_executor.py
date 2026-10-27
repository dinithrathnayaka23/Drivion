"""The action registry and the safety executor (pure logic, no Windows calls)."""

import pytest

from drivion.actions.registry import ActionRegistry, ActionResult, Risk
from drivion.intents import schemas as s
from drivion.safety.executor import NOT_ALLOWED, Done, NeedsConfirmation, Refused, SafeExecutor


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def ran():
    return []


@pytest.fixture
def registry(ran):
    r = ActionRegistry()
    r.register("SET_VOLUME", "volume", Risk.LOW,
               lambda i: ran.append(i) or ActionResult(True, "Volume set.", verified=True))
    r.register("SHUTDOWN_COMPUTER", "shut down", Risk.HIGH,
               lambda i: ran.append(i) or ActionResult(True, "Shutting down."))
    r.register("LOCK_COMPUTER", "lock", Risk.MEDIUM,
               lambda i: (_ for _ in ()).throw(RuntimeError("driver bug")))
    return r


@pytest.fixture
def state():
    return {"authorized": True}


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def executor(registry, state, clock):
    return SafeExecutor(registry, lambda: state["authorized"], confirmation_timeout_s=15, clock=clock)


# ----- registry ------------------------------------------------------------------------


def test_registry_rejects_unknown_and_duplicate_kinds():
    r = ActionRegistry()
    with pytest.raises(ValueError, match="not a known intent"):
        r.register("RUN_SHELL", "x", Risk.LOW, lambda i: None)
    r.register("MUTE", "mute", Risk.LOW, lambda i: None)
    with pytest.raises(ValueError, match="already registered"):
        r.register("MUTE", "again", Risk.LOW, lambda i: None)


def test_only_high_risk_needs_confirmation(registry):
    assert registry.get("SHUTDOWN_COMPUTER").needs_confirmation
    assert not registry.get("SET_VOLUME").needs_confirmation
    assert not registry.get("LOCK_COMPUTER").needs_confirmation


# ----- executor ---------------------------------------------------------------------------


def test_low_risk_runs_immediately(executor, ran):
    decision = executor.request(s.SetVolume(percent=40))
    assert isinstance(decision, Done) and decision.result.success
    assert ran == [s.SetVolume(percent=40)]


def test_unregistered_action_is_refused(executor, ran):
    decision = executor.request(s.TakeScreenshot())
    assert isinstance(decision, Refused)
    assert ran == []


@pytest.mark.parametrize("check", [lambda: False, lambda: 1 / 0])  # "no", or the check itself fails
def test_fails_closed_when_not_authorized(registry, ran, check):
    executor = SafeExecutor(registry, check)
    assert executor.request(s.SetVolume(percent=40)) == Refused(NOT_ALLOWED)
    assert executor.request(s.ShutdownComputer()) == Refused(NOT_ALLOWED)
    assert ran == []


def test_high_risk_waits_for_yes(executor, ran):
    decision = executor.request(s.ShutdownComputer())
    assert isinstance(decision, NeedsConfirmation)
    assert "shut down the computer" in decision.prompt
    assert ran == [] and executor.has_pending
    confirmed = executor.confirm()
    assert isinstance(confirmed, Done)
    assert ran == [s.ShutdownComputer()]
    assert not executor.has_pending
    assert executor.confirm() is None  # a second "yes" does nothing


def test_confirmation_expires(executor, ran, clock):
    executor.request(s.ShutdownComputer())
    clock.now += 15.1
    assert not executor.has_pending
    assert executor.confirm() is None
    assert ran == []


def test_authorization_is_checked_again_on_confirm(executor, ran, state):
    executor.request(s.ShutdownComputer())
    state["authorized"] = False  # e.g. Drivion went back to standby meanwhile
    assert executor.confirm() == Refused(NOT_ALLOWED)
    assert ran == []


def test_drop_pending(executor, ran):
    executor.request(s.ShutdownComputer())
    assert executor.drop_pending("user said no") == s.ShutdownComputer()
    assert executor.confirm() is None
    assert executor.drop_pending("again") is None
    assert ran == []


def test_a_crashing_handler_becomes_a_failed_result(executor):
    decision = executor.request(s.LockComputer())
    assert isinstance(decision, Done)
    assert not decision.result.success
    assert "couldn't lock the computer" in decision.result.message


def test_every_decision_is_audited(executor, caplog):
    with caplog.at_level("INFO", logger="drivion.audit"):
        executor.request(s.SetVolume(percent=40))
        executor.request(s.ShutdownComputer())
        executor.drop_pending("test")
    text = caplog.text
    assert "DONE SET_VOLUME" in text and "PENDING SHUTDOWN_COMPUTER" in text and "DROPPED" in text
