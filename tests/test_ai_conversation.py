"""The responder with the AI fallback: real parser, executor and handlers; fake AI and backends."""

import pytest

from action_fakes import FakePower, fake_backends
from drivion.actions.handlers import PowerScheduler, build_registry
from drivion.config.settings import ActionsSettings, CommandsSettings
from drivion.core.activity import Outcome
from drivion.intents import schemas as s
from drivion.intents.catalog import Catalog
from drivion.intents.responder import AI_UNREACHABLE_REPLY, NO_AI_KEY_REPLY, AssistantResponder
from drivion.llm.assistant import LLMAssistant
from drivion.llm.fallback import FallbackChat
from drivion.llm.providers import ProviderUnavailable
from drivion.safety.executor import NOT_ALLOWED, SafeExecutor
from llm_fakes import FakeTransport, action, answer, provider


class Harness:
    def __init__(self, tmp_path, script, keys=True):
        self.transport = FakeTransport(script)
        self.power = FakePower()
        self.backends = fake_backends(power=self.power)
        self.unlocked = True
        self.thinking = 0
        commands = CommandsSettings()
        catalog = Catalog.from_settings(commands)
        scheduler = PowerScheduler(self.power, 10, False, notify=lambda m: None, sleep_delay_s=60)
        registry = build_registry(self.backends, commands, ActionsSettings(screenshot_dir=str(tmp_path)),
                                  catalog.spoken_name, scheduler, wait=lambda c, t: c())
        executor = SafeExecutor(registry, lambda: self.unlocked,
                                describe=lambda i: s.describe(i, catalog.spoken_name))
        key = "test-key-123" if keys else None
        chat = FallbackChat([provider("gemini", self.transport, key=key),
                             provider("groq", self.transport, key=key)], 5, 100)
        self.responder = AssistantResponder(
            catalog, on_go_to_sleep=lambda: None, wake_phrase="Hey Jarvis", executor=executor,
            cancel_scheduled=scheduler.cancel, llm=LLMAssistant(chat, catalog),
            on_thinking=self._think)

    def _think(self):
        self.thinking += 1

    def say(self, text):
        return self.responder(text)


def test_simple_commands_never_leave_the_computer(tmp_path):
    h = Harness(tmp_path, {})
    for text in ["Set the volume to 40%.", "Open Chrome.", "Help.", "Take a screenshot.", "Mute."]:
        h.say(text)
    assert h.transport.requests == []  # the offline parser handled all of them
    assert h.thinking == 0


def test_questions_are_answered_by_the_ai(tmp_path):
    h = Harness(tmp_path, {"gemini": [answer("Paris is the capital of France.")]})
    assert h.say("What is the capital of France?") == ("Paris is the capital of France.", Outcome.SUCCESS)
    assert h.thinking == 1


def test_ai_turns_a_free_form_request_into_a_real_action(tmp_path):
    h = Harness(tmp_path, {"gemini": [action(kind="SET_VOLUME", percent=80)]})
    reply, outcome = h.say("I can barely hear anything, crank it right up.")
    assert (reply, outcome) == ("Volume set to 80%.", Outcome.SUCCESS)
    assert h.backends.volume.percent == 80


def test_ai_chosen_shutdown_still_needs_your_yes(tmp_path):
    h = Harness(tmp_path, {"gemini": [action(kind="SHUTDOWN_COMPUTER")]})
    reply, outcome = h.say("I'm done for today, turn everything off.")
    assert outcome is Outcome.PENDING and "Are you sure" in reply
    assert h.power.calls == []
    assert h.say("Yes.")[1] is Outcome.SUCCESS  # your yes, parsed offline - not the AI's
    assert h.power.calls == [("shutdown", 10)]


def test_ai_can_never_confirm_for_you(tmp_path):
    # A pending shutdown, then an unclear reply that goes to the AI, which tries to say yes.
    h = Harness(tmp_path, {"gemini": [action(kind="CONFIRM")], "groq": [answer("Okay.")]})
    h.say("Shut down the computer.")
    reply, _ = h.say("Hmm, whatever you think is best really.")
    assert reply.startswith("I've cancelled the request to shut down the computer.")
    h.say("Yes.")  # the request is already gone
    assert h.power.calls == []


def test_ai_actions_are_refused_while_locked(tmp_path):
    h = Harness(tmp_path, {"gemini": [action(kind="SET_VOLUME", percent=10)]})
    h.unlocked = False
    assert h.say("Turn the noise way down please, it's late.") == (NOT_ALLOWED, Outcome.REJECTED)
    assert h.backends.volume.percent == 40


def test_ai_cannot_open_things_outside_the_allowlist(tmp_path):
    h = Harness(tmp_path, {"gemini": [action(kind="OPEN_APP", app="cmd")],
                           "groq": [answer("I can't open that.")]})
    # (The offline parser already refuses "open a command prompt"; this phrasing reaches the AI.)
    reply = h.say("I need somewhere to type terminal commands.")
    assert reply == ("I can't open that.", Outcome.SUCCESS)
    assert [r["provider"] for r in h.transport.requests] == ["gemini", "groq"]  # gemini's reply rejected
    assert h.backends.desktop.opened == []


def test_no_keys_explains_how_to_set_one_up(tmp_path):
    h = Harness(tmp_path, {}, keys=False)
    assert h.say("Who wrote Hamlet?") == (NO_AI_KEY_REPLY, Outcome.REJECTED)
    assert h.transport.requests == [] and h.thinking == 0


def test_network_down_everywhere(tmp_path):
    h = Harness(tmp_path, {"gemini": [ProviderUnavailable("offline")], "groq": [ProviderUnavailable("offline")]})
    assert h.say("Who wrote Hamlet?") == (AI_UNREACHABLE_REPLY, Outcome.FAILED)


def test_fallback_answers_when_the_first_provider_is_rate_limited(tmp_path):
    h = Harness(tmp_path, {"gemini": [(429, b"{}")], "groq": [answer("Shakespeare.")]})
    assert h.say("Who wrote Hamlet?") == ("Shakespeare.", Outcome.SUCCESS)


def test_help_mentions_questions_when_ai_is_set_up(tmp_path):
    assert "general questions" in Harness(tmp_path, {}).say("Help.")[0]
    assert "general questions" not in Harness(tmp_path, {}, keys=False).say("Help.")[0]
