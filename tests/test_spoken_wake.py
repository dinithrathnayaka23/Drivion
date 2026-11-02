"""Waking on "Hey Drivion" with the speech recognizer."""

import os
import sys
from pathlib import Path

import numpy as np
import pytest

from audio_fakes import synthesize_speech
from drivion.audio.spoken_wake import SpokenWakeEngine, boosted, says_wake_phrase
from drivion.config import AppConfig
from drivion.doctor import Status, run_checks
from drivion.config import load_secrets
from drivion.speech.stt import Transcript, WhisperTranscriber, whisper_model_dir
from drivion.speech.vad import VAD_FRAME_SAMPLES, SileroVad
from drivion.vision.templates import TemplateStore

MODEL = whisper_model_dir(Path(os.environ.get("LOCALAPPDATA", "")) / "Drivion" / "models", "base.en")


@pytest.mark.parametrize("text", [
    "Hey Drivion", "Hey, Drivian!", "Hey. Dravian.", "hey drivy on", "Hey drive Eon",
    "Hi Drivion", "Hey Drivion, are you there?", "so hey drivion", "Hey, drive E on.",
    "Hey, Drubian.", "Hey, Tribune", "Hey, Drew Bien",  # what a real voice produced
])
def test_the_phrase_and_how_whisper_spells_it(text):
    assert says_wake_phrase(text)


@pytest.mark.parametrize("text", [
    "", "Drivion", "Hey", "Hey driving", "Hey Vivian", "Hey division", "Hey Damian", "Hey Brian",
    "Driving home today", "Drivion hey", "Hey there Drivion", "hey you", "A driven person",
    "Hey Trevor", "Hey Dorian", "Hey Adrian", "Hey Jordan", "Hey Julian", "Hey Marion", "Hey Dravid",
    "Hey Darwin", "Hey driven", "Hey Caribbean", "Hey Robin", "Hey Devin", "Hey oblivion", "Hey Dave",
])
def test_lookalikes_do_not_wake(text):
    assert not says_wake_phrase(text)


class FakeTranscriber:
    def __init__(self, text):
        self.text, self.calls = text, 0

    def transcribe(self, audio):
        self.calls += 1
        return Transcript(self.text, 0.1)


def run_engine(text, speech=(0.0, 0.9)):
    """Half a second of silence, one second of speech, then silence."""
    transcriber = FakeTranscriber(text)
    levels = iter([speech[0]] * 8 + [speech[1]] * 16 + [speech[0]] * 16)
    engine = SpokenWakeEngine(lambda: lambda frame: next(levels), lambda: transcriber)
    engine.reset()
    frame = np.zeros(VAD_FRAME_SAMPLES, dtype=np.int16)
    return [engine.process(frame) for _ in range(40)], transcriber


def test_a_burst_saying_the_phrase_scores_once_when_it_ends():
    scores, transcriber = run_engine("Hey Drivion.")
    assert sum(score == 1.0 for score in scores) == 1 and transcriber.calls == 1


def test_a_burst_saying_something_else_scores_nothing():
    scores, _ = run_engine("What's for dinner?")
    assert max(scores) == 0.0


def test_silence_never_reaches_the_recognizer():
    scores, transcriber = run_engine("Hey Drivion", speech=(0.0, 0.0))
    assert max(scores) == 0.0 and transcriber.calls == 0


def test_quiet_audio_is_boosted_and_silence_is_not():
    quiet = np.array([0, 500, -500], dtype=np.int16)
    assert abs(boosted(quiet)).max() > 5_000
    silent = np.array([0, 5, -5], dtype=np.int16)
    assert boosted(silent) is silent
    loud = np.array([0, 30_000], dtype=np.int16)
    assert boosted(loud) is loud


def test_a_quiet_burst_the_vad_misses_still_reaches_the_recognizer():
    transcriber = FakeTranscriber("Hey Drivion")
    engine = SpokenWakeEngine(lambda: lambda frame: 0.0, lambda: transcriber)
    engine.reset()
    room = np.full(VAD_FRAME_SAMPLES, 3, dtype=np.int16)
    voice = (np.sin(np.arange(VAD_FRAME_SAMPLES) / 5) * 400).astype(np.int16)
    scores = [engine.process(frame) for frame in [room] * 30 + [voice] * 12 + [room] * 12]
    assert max(scores) == 1.0 and transcriber.calls == 1


def test_steady_room_noise_settles_and_stops_counting_as_sound():
    transcriber = FakeTranscriber("")
    engine = SpokenWakeEngine(lambda: lambda frame: 0.0, lambda: transcriber)
    engine.reset()
    noise = np.random.default_rng(1).normal(0, 200, VAD_FRAME_SAMPLES).astype(np.int16)
    for _ in range(100):
        engine.process(noise)
    assert transcriber.calls == 0


def test_the_test_tool_is_told_what_was_heard():
    heard = []
    levels = iter([0.9] * 16 + [0.0] * 16)
    engine = SpokenWakeEngine(lambda: lambda frame: next(levels), lambda: FakeTranscriber("Hey Drivion"),
                              on_heard=lambda text, woke: heard.append((text, woke)))
    engine.reset()
    for _ in range(32):
        engine.process(np.zeros(VAD_FRAME_SAMPLES, dtype=np.int16))
    assert heard == [("Hey Drivion", True)]


class Scripted:
    def __init__(self, *texts):
        self.texts = iter(texts)

    def transcribe(self, audio):
        return Transcript(next(self.texts), 0.1)


def bursts(engine, count, gap_frames):
    """``count`` short bursts of speech, separated by silence."""
    levels = ([0.9] * 8 + [0.0] * gap_frames) * count
    engine._vad = lambda frame, it=iter(levels): next(it)
    frame = np.zeros(VAD_FRAME_SAMPLES, dtype=np.int16)
    return [engine.process(frame) for _ in levels]


def split_engine(*texts):
    engine = SpokenWakeEngine(lambda: lambda frame: 0.0, lambda: Scripted(*texts))
    engine.reset()
    return engine


def test_a_pause_after_hey_does_not_lose_the_phrase():
    assert max(bursts(split_engine("Hey.", "Drivian."), 2, 10)) == 1.0


def test_words_far_apart_are_not_joined():
    assert max(bursts(split_engine("Hey.", "Drivian."), 2, 60)) == 0.0


def test_models_load_before_listening_and_only_once():
    loads = []
    engine = SpokenWakeEngine(lambda: loads.append("vad") or (lambda frame: 0.0),
                              lambda: loads.append("speech") or FakeTranscriber(""))
    engine.reset()
    engine.reset()
    assert loads == ["vad", "speech"]


def test_nothing_heard_is_logged(caplog):
    with caplog.at_level("DEBUG"):
        run_engine("my private conversation")
    assert "private" not in caplog.text


def test_doctor_checks_the_speech_model_for_this_wake_word(tmp_path):
    checks = run_checks(AppConfig(), load_secrets(tmp_path / ".env"), hardware=False,
                        store=TemplateStore(tmp_path / "face"), models=tmp_path / "models")
    check = next(c for c in checks if c.name == "Wake word")
    assert check.status is Status.FAIL and "--download-models" in check.fix


@pytest.mark.skipif(sys.platform != "win32", reason="uses Windows speech synthesis")
@pytest.mark.skipif(not (MODEL / "model.bin").exists(), reason="run `drivion --download-models`")
@pytest.mark.parametrize("spoken, wakes", [("Hey Drivion", True), ("Hey Vivian", False),
                                           ("Set the volume to forty percent", False)])
def test_real_speech_through_the_real_models(spoken, wakes, tmp_path):
    import wave

    synthesize_speech(spoken, tmp_path / "phrase.wav")
    with wave.open(str(tmp_path / "phrase.wav")) as w:
        speech = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    audio = np.concatenate([np.zeros(16_000, np.int16), speech, np.zeros(24_000, np.int16)])
    usable = len(audio) - len(audio) % VAD_FRAME_SAMPLES

    engine = SpokenWakeEngine(SileroVad, lambda: WhisperTranscriber(MODEL))
    engine.reset()
    scores = [engine.process(frame) for frame in audio[:usable].reshape(-1, VAD_FRAME_SAMPLES)]
    assert (max(scores) == 1.0) is wakes
