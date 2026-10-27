import sys
import threading
import time

import pytest

from drivion.core.activity import ActivityFeed, Outcome
from drivion.core.commands import ERROR_REPLY, UNCLEAR_REPLY, CommandProcessor
from drivion.speech.tts import SilentSpeaker, WindowsSpeaker


class RecordingSpeaker:
    is_speaking = False

    def __init__(self):
        self.said = []

    def say(self, text):
        self.said.append(text)

    def cancel(self):
        pass


# ----- command processor ------------------------------------------------------------


def test_processor_records_and_speaks_reply(qapp):
    feed, speaker = ActivityFeed(), RecordingSpeaker()
    CommandProcessor(feed, speaker, lambda t: ("Done.", Outcome.SUCCESS)).handle("open chrome")
    record = feed.history[0]
    assert (record.command, record.response, record.outcome) == ("open chrome", "Done.", Outcome.SUCCESS)
    assert speaker.said == ["Done."]


def test_processor_survives_a_broken_responder(qapp):
    feed, speaker = ActivityFeed(), RecordingSpeaker()

    def broken(text):
        raise RuntimeError("bug")

    CommandProcessor(feed, speaker, broken).handle("open chrome")
    assert feed.history[0].outcome is Outcome.FAILED
    assert speaker.said == [ERROR_REPLY]


def test_unclear_speech_gets_a_spoken_hint_but_no_history(qapp):
    feed, speaker = ActivityFeed(), RecordingSpeaker()
    CommandProcessor(feed, speaker, lambda t: ("unused", Outcome.SUCCESS)).unclear()
    assert feed.history == []
    assert speaker.said == [UNCLEAR_REPLY]


def test_silent_speaker_never_reports_speaking():
    speaker = SilentSpeaker()
    speaker.say("hello")
    assert speaker.is_speaking is False


# ----- the real Windows speech engine, at volume 0 (no sound) ---------------------

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows speech (SAPI)")


def wait_for(condition, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def speaker():
    s = WindowsSpeaker(volume=0)
    s.start()
    yield s
    s.stop(timeout=3)


@windows_only
def test_is_speaking_is_true_from_the_moment_text_is_queued(speaker):
    assert wait_for(lambda: speaker.is_running)
    speaker.say("This is a test of the Drivion speech output.")
    assert speaker.is_speaking  # immediately, before audio starts
    assert wait_for(lambda: not speaker.is_speaking, timeout=15)
    assert speaker.available


@windows_only
def test_cancel_stops_a_long_sentence_quickly(speaker):
    assert wait_for(lambda: speaker.is_running)
    speaker.say("This sentence is deliberately long. " * 20)
    speaker.say("And this queued one should never be spoken.")
    time.sleep(0.3)
    started = time.monotonic()
    speaker.cancel()
    assert wait_for(lambda: not speaker.is_speaking, timeout=3)
    assert time.monotonic() - started < 1.0


@windows_only
def test_stop_interrupts_speech_and_ends_the_thread(speaker):
    assert wait_for(lambda: speaker.is_running)
    speaker.say("This sentence is deliberately long. " * 20)
    time.sleep(0.2)
    assert speaker.stop(timeout=2) is True
    assert not speaker.is_speaking


@windows_only
def test_unknown_voice_falls_back_to_default():
    s = WindowsSpeaker(voice="No Such Voice", volume=0)
    s.start()
    try:
        assert wait_for(lambda: s.is_running)
        s.say("Hello.")
        assert wait_for(lambda: not s.is_speaking, timeout=10)
        assert s.available
    finally:
        s.stop()


def test_say_before_start_is_a_harmless_no_op():
    s = WindowsSpeaker(volume=0)
    s.say("Nobody is listening.")
    assert not s.is_speaking


@windows_only
def test_speaker_thread_is_not_the_caller(speaker):
    callers = []
    speaker._speak = lambda voice, text, stop: callers.append(threading.current_thread())
    assert wait_for(lambda: speaker.is_running)
    speaker.say("thread check")
    assert wait_for(lambda: callers)
    assert callers[0] is not threading.main_thread()
