"""Integration: the real openWakeWord engine on recorded (synthesized) speech.

Uses the models from `drivion --download-models` in the real per-user
folder and Windows' built-in voice to produce audio, so no microphone is
needed. Skipped when either isn't available.
"""

import os
import sys
import threading
from pathlib import Path

import pytest

from audio_fakes import FakeSource, synthesize_speech, wav_frames
from drivion.audio.wake_word import (
    OpenWakeWordEngine,
    WakeWordDetector,
    WakeWordService,
    resolve_wake_word,
    sensitivity_to_threshold,
)
from drivion.core.activity import DeviceState

REAL_MODELS = Path(os.environ.get("LOCALAPPDATA", "")) / "Drivion" / "models"

pytestmark = [
    pytest.mark.skipif(sys.platform != "win32", reason="uses Windows speech synthesis"),
    pytest.mark.skipif(
        not (REAL_MODELS / "hey_jarvis_v0.1.onnx").exists(),
        reason="run `drivion --download-models` first",
    ),
]


@pytest.fixture(scope="module")
def engine():
    path, _ = resolve_wake_word("hey_jarvis", REAL_MODELS, None)
    return OpenWakeWordEngine(path, REAL_MODELS)


def listen_to(engine, frames):
    detections, done = [], threading.Event()
    service = WakeWordService(
        source_factory=lambda: FakeSource(frames),
        engine=engine,
        detector=WakeWordDetector(sensitivity_to_threshold(0.5), cooldown_s=2.0),
        on_detected=detections.append,
        on_microphone=lambda s: s is not DeviceState.ACTIVE and done.set(),
    )
    service.start()
    assert done.wait(30)
    service.stop()
    return detections


@pytest.mark.parametrize("phrase", ["Hey Jarvis", "Hey, Jarvis!"])
def test_wake_phrase_is_detected_once(engine, tmp_path, phrase):
    wav = tmp_path / "wake.wav"
    synthesize_speech(phrase, wav)
    detections = listen_to(engine, wav_frames(wav))
    assert len(detections) == 1
    assert detections[0] >= 0.5


@pytest.mark.parametrize(
    "sentence",
    ["Good morning, what is the weather like today", "Open the file explorer please", "Harvest"],
)
def test_other_speech_does_not_trigger(engine, tmp_path, sentence):
    wav = tmp_path / "other.wav"
    synthesize_speech(sentence, wav)
    assert listen_to(engine, wav_frames(wav)) == []
