"""The responder: what Drivion says and does for each recognised command."""

import threading

import pytest

from drivion.config.settings import CommandsSettings
from drivion.core.activity import Outcome
from drivion.intents.catalog import Catalog
from drivion.intents.responder import (
    NOT_UNDERSTOOD_REPLY,
    NOTHING_TO_CANCEL,
    NOTHING_TO_CONFIRM,
    NOTHING_TO_REPEAT,
    QUESTION_REPLY,
    AssistantResponder,
)


@pytest.fixture
def slept():
    return []


@pytest.fixture
def responder(slept):
    c = CommandsSettings()
    return AssistantResponder(Catalog.from_settings(c),
                              on_go_to_sleep=lambda: slept.append(True), wake_phrase="Hey Jarvis")


def test_go_to_sleep_requests_standby(responder, slept):
    reply, outcome = responder("Drivion, go to sleep.")
    assert slept == [True]
    assert outcome is Outcome.SUCCESS
    assert "Hey Jarvis" in reply


def test_computer_sleep_does_not_put_drivion_to_sleep(responder, slept):
    reply, outcome = responder("Put my computer to sleep.")
    assert slept == []
    assert outcome is Outcome.REJECTED
    assert "put the computer to sleep" in reply and "can't" in reply


def test_system_commands_are_understood_but_not_executed_yet(responder):
    reply, outcome = responder("Set the volume to 40%.")
    assert reply == "I understood: set the volume to 40%. I can't control the computer yet."
    assert outcome is Outcome.REJECTED
    assert "vs code" in responder("Open VS Code.")[0]


def test_invalid_and_unknown_replies(responder):
    assert responder("Set the volume to 150%.") == (
        "The volume must be between 0 and 100 percent.", Outcome.REJECTED)
    assert responder("Banana.") == (NOT_UNDERSTOOD_REPLY, Outcome.REJECTED)
    assert responder("What time is it?") == (QUESTION_REPLY, Outcome.REJECTED)


def test_repeat_says_the_last_answer_again(responder):
    assert responder("Repeat.") == (NOTHING_TO_REPEAT, Outcome.SUCCESS)
    first, _ = responder("Set the volume to 40%.")
    assert responder("Repeat that.") == (first, Outcome.SUCCESS)
    assert responder("Say that again.") == (first, Outcome.SUCCESS)  # repeat doesn't replace it


def test_help_mentions_real_examples_and_is_honest(responder):
    reply, outcome = responder("What can you do?")
    assert outcome is Outcome.SUCCESS
    assert "open google chrome" in reply
    assert "can't carry out the computer ones yet" in reply


def test_cancel_confirm_and_greeting(responder):
    assert responder("Never mind.") == (NOTHING_TO_CANCEL, Outcome.SUCCESS)
    assert responder("Yes.") == (NOTHING_TO_CONFIRM, Outcome.REJECTED)
    assert responder("Hey Drivion.")[1] is Outcome.SUCCESS


def test_responder_is_safe_to_call_from_several_threads(responder):
    errors = []

    def worker():
        try:
            for _ in range(50):
                responder("Set the volume to 40%.")
                responder("Repeat.")
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
