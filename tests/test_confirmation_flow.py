"""The whole spoken flow - responder + safety executor + handlers - with fake backends.

These are the conversations that matter most for safety: power actions
must only ever happen after an explicit "yes", while Drivion is unlocked.
"""

import pytest

from action_fakes import FakePower, fake_backends
from drivion.actions.handlers import PowerScheduler, build_registry
from drivion.config.settings import ActionsSettings, CommandsSettings
from drivion.core.activity import Outcome
from drivion.intents import schemas as s
from drivion.intents.catalog import Catalog
from drivion.intents.responder import NOTHING_TO_CANCEL, NOTHING_TO_CONFIRM, AssistantResponder
from drivion.safety.executor import NOT_ALLOWED, SafeExecutor


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Harness:
    def __init__(self, tmp_path):
        self.power = FakePower()
        self.backends = fake_backends(power=self.power)
        self.clock = Clock()
        self.unlocked = True
        commands = CommandsSettings()
        catalog = Catalog.from_settings(commands)
        self.scheduler = PowerScheduler(self.power, 10, False, notify=lambda m: None,
                                        sleep_delay_s=60, clock=self.clock)
        registry = build_registry(self.backends, commands,
                                  ActionsSettings(screenshot_dir=str(tmp_path)),
                                  catalog.spoken_name, self.scheduler, wait=lambda c, t: c())
        executor = SafeExecutor(registry, lambda: self.unlocked, confirmation_timeout_s=15,
                                describe=lambda i: s.describe(i, catalog.spoken_name), clock=self.clock)
        self.responder = AssistantResponder(catalog, on_go_to_sleep=lambda: None,
                                            wake_phrase="Hey Jarvis", executor=executor,
                                            cancel_scheduled=self.scheduler.cancel)

    def say(self, text):
        return self.responder(text)

    @property
    def power_calls(self):
        return [c for c in self.power.calls if c[0] != "abort"]


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


def test_low_risk_command_runs_straight_away(h):
    assert h.say("Set the volume to 65%.") == ("Volume set to 65%.", Outcome.SUCCESS)
    assert h.backends.volume.percent == 65


def test_shutdown_needs_an_explicit_yes(h):
    reply, outcome = h.say("Shut down the computer.")
    assert outcome is Outcome.PENDING
    assert reply == "Are you sure you want me to shut down the computer? Say yes or no."
    assert h.power_calls == []

    reply, outcome = h.say("Yes.")
    assert outcome is Outcome.SUCCESS
    assert reply == "The computer will shut down in 10 seconds. Say cancel to stop it."
    assert h.power_calls == [("shutdown", 10)]


@pytest.mark.parametrize("answer", ["No.", "Nope.", "Cancel.", "Never mind.", "Don't do it."])
def test_no_or_cancel_means_nothing_happens(h, answer):
    h.say("Restart the computer.")
    reply, outcome = h.say(answer)
    assert reply == "Okay, I won't restart the computer."
    assert h.power_calls == []
    assert h.say("Yes.") == (NOTHING_TO_CONFIRM, Outcome.REJECTED)  # the request is gone


@pytest.mark.parametrize("other", ["Set the volume to 20%.", "Banana.", "What time is it?",
                                   "Set the volume to 150%."])
def test_anything_else_cancels_the_request_and_is_never_consent(h, other):
    h.say("Put my computer to sleep.")
    reply, _ = h.say(other)
    assert reply.startswith("I've cancelled the request to put the computer to sleep.")
    h.say("Yes.")
    assert h.power_calls == []


def test_a_late_yes_does_nothing(h):
    h.say("Shut down the computer.")
    h.clock.now += 16  # confirmation window is 15 s
    assert h.say("Yes.") == (NOTHING_TO_CONFIRM, Outcome.REJECTED)
    assert h.power_calls == []


def test_yes_after_drivion_locked_again_is_refused(h):
    h.say("Shut down the computer.")
    h.unlocked = False
    assert h.say("Yes.") == (NOT_ALLOWED, Outcome.REJECTED)
    assert h.power_calls == []


def test_nothing_runs_while_locked(h):
    h.unlocked = False
    assert h.say("Set the volume to 10%.") == (NOT_ALLOWED, Outcome.REJECTED)
    assert h.say("Shut down the computer.") == (NOT_ALLOWED, Outcome.REJECTED)
    assert h.backends.volume.percent == 40 and h.power_calls == []


def test_cancel_after_yes_aborts_the_scheduled_shutdown(h):
    h.say("Shut down the computer.")
    h.say("Yes.")
    h.clock.now += 4
    assert h.say("Cancel.") == ("Okay, I've cancelled the shut down.", Outcome.SUCCESS)
    assert h.power.calls[-1] == ("abort",)
    assert h.say("Cancel.") == (NOTHING_TO_CANCEL, Outcome.SUCCESS)


def test_cancel_stops_a_pending_sleep(h):
    h.say("Put my computer to sleep.")
    assert h.say("Yes.")[0] == "The computer will go to sleep in 60 seconds."
    assert h.say("Cancel.") == ("Okay, the computer won't go to sleep.", Outcome.SUCCESS)
    assert h.power_calls == []


def test_go_to_sleep_is_never_a_power_action(h):
    h.say("Drivion, go to sleep.")
    h.say("Yes.")
    assert h.power_calls == []


def test_failures_are_reported_as_failed(h):
    reply, outcome = h.say("Minimize Chrome.")  # no Chrome windows in the fake desktop
    assert (reply, outcome) == ("Google chrome isn't open.", Outcome.FAILED)


def test_help_mentions_confirmation(h):
    assert "always ask you to confirm" in h.say("Help.")[0]
