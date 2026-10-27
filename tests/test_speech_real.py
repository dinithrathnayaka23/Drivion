"""Integration: real Silero VAD + real Whisper on recorded (synthesized) speech.

Audio comes from Windows' built-in voice, so no microphone is needed. Uses
the speech model from `drivion --download-models`; skipped without it.
"""

import os
import sys
import threading
from pathlib import Path

import numpy as np
import pytest

from audio_fakes import FakeSource, synthesize_speech
from drivion.core.activity import DeviceState
from drivion.speech.listener import CommandListenerService
from drivion.speech.recorder import RecorderSettings
from drivion.speech.stt import WhisperTranscriber, whisper_model_dir
from drivion.speech.tts import SilentSpeaker
from drivion.speech.vad import VAD_FRAME_SAMPLES, SileroVad

MODEL = whisper_model_dir(Path(os.environ.get("LOCALAPPDATA", "")) / "Drivion" / "models", "base.en")

pytestmark = [
    pytest.mark.skipif(sys.platform != "win32", reason="uses Windows speech synthesis"),
    pytest.mark.skipif(not (MODEL / "model.bin").exists(), reason="run `drivion --download-models`"),
]


@pytest.fixture(scope="module")
def transcriber():
    return WhisperTranscriber(MODEL)


def frames_of(*chunks):
    audio = np.concatenate(chunks)
    usable = len(audio) - len(audio) % VAD_FRAME_SAMPLES
    return list(audio[:usable].reshape(-1, VAD_FRAME_SAMPLES))


def wav_audio(text, path):
    import wave

    synthesize_speech(text, path)
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def silence(seconds):
    return np.zeros(int(16000 * seconds), dtype=np.int16)


def listen(transcriber, frames):
    commands, unclear, done = [], [], threading.Event()
    service = CommandListenerService(
        source_factory=lambda: FakeSource(frames),
        vad_factory=SileroVad,
        transcriber_factory=lambda: transcriber,
        speaker=SilentSpeaker(),
        recorder_settings=RecorderSettings(),
        command_timeout_s=60,
        on_command=commands.append,
        on_unclear=lambda: unclear.append(True),
        on_timeout=lambda: None,
        on_microphone=lambda s: s is not DeviceState.ACTIVE and done.set(),
        on_status=lambda s: None,
    )
    service.start()
    assert done.wait(60)
    service.stop()
    return commands, unclear


def normalise(text):
    return "".join(c for c in text.lower() if c.isalnum() or c == " ").split()


def test_two_spoken_commands_are_transcribed(transcriber, tmp_path):
    first = wav_audio("Open Chrome", tmp_path / "a.wav")
    second = wav_audio("Set the volume to forty percent", tmp_path / "b.wav")
    commands, unclear = listen(
        transcriber, frames_of(silence(1), first, silence(1.5), second, silence(1.5))
    )
    assert len(commands) == 2, commands
    assert normalise(commands[0]) == ["open", "chrome"]
    assert "volume" in normalise(commands[1])
    assert any(word in commands[1].lower() for word in ("40", "forty"))
    assert unclear == []


def test_silence_and_room_noise_produce_no_command(transcriber):
    hiss = np.random.default_rng(1).normal(0, 300, 16000 * 4).astype(np.int16)
    commands, unclear = listen(transcriber, frames_of(silence(3), hiss, silence(3)))
    assert commands == []
    assert unclear == []  # the VAD never even passed it to Whisper


@pytest.mark.parametrize(
    "spoken, expected",
    [
        ("Open Chrome", "OPEN_APP"),
        ("Set the volume to forty percent", "SET_VOLUME"),
        ("Drivion, go to sleep", "GO_TO_SLEEP"),
        ("Put my computer to sleep", "SLEEP_COMPUTER"),
        ("Take a screenshot", "TAKE_SCREENSHOT"),
        ("What can you do", "HELP"),
    ],
)
def test_spoken_commands_are_understood_end_to_end(transcriber, tmp_path, spoken, expected):
    """Synthesized speech -> real VAD + Whisper -> rule-based parser."""
    from drivion.config.settings import CommandsSettings
    from drivion.intents.catalog import Catalog
    from drivion.intents.parser import IntentParser, Understood

    audio = wav_audio(spoken, tmp_path / "cmd.wav")
    commands, _ = listen(transcriber, frames_of(silence(1), audio, silence(1.5)))
    assert len(commands) == 1, commands
    c = CommandsSettings()
    result = IntentParser(Catalog.from_settings(c)).parse(commands[0])
    assert isinstance(result, Understood), (commands[0], result)
    assert result.intent.kind == expected, (commands[0], result.intent)
