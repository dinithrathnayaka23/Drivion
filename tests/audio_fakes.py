"""Test doubles for audio: no microphone needed."""

from __future__ import annotations

import os
import subprocess
import threading
import wave
from pathlib import Path

import numpy as np

from drivion.audio.source import FRAME_SAMPLES, SAMPLE_RATE, AudioDeviceError


class FakeSource:
    """Plays back a list of frames, then ends (or loops silence forever)."""

    def __init__(self, frames=None, endless=False, fail_open=False, fail_on_read=None):
        self.frames = list(frames or [])
        self.endless = endless
        self.fail_open = fail_open
        self.fail_on_read = fail_on_read  # index of the read that raises
        self.opened = self.closed = False
        self.reads = 0

    def open(self):
        if self.fail_open:
            raise AudioDeviceError("no microphone (fake)")
        self.opened = True

    def read(self):
        if self.fail_on_read is not None and self.reads == self.fail_on_read:
            raise AudioDeviceError("device unplugged (fake)")
        self.reads += 1
        if self.frames:
            return self.frames.pop(0)
        if self.endless:
            threading.Event().wait(0.005)  # behave like a real blocking read
            return np.zeros(FRAME_SAMPLES, dtype=np.int16)
        return None

    def close(self):
        self.closed = True


class ScriptedEngine:
    """Returns pre-set scores, one per frame (0.0 once the script runs out)."""

    def __init__(self, scores=()):
        self.scores = list(scores)
        self.resets = 0
        self.frames_seen = 0

    def process(self, frame):
        self.frames_seen += 1
        return self.scores.pop(0) if self.scores else 0.0

    def reset(self):
        self.resets += 1


def silent_frames(count):
    return [np.zeros(FRAME_SAMPLES, dtype=np.int16) for _ in range(count)]


def wav_frames(path: Path, pad_seconds: float = 1.0) -> list[np.ndarray]:
    """Split a 16 kHz mono 16-bit WAV into frames, padded with silence."""
    with wave.open(str(path)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (SAMPLE_RATE, 1, 2)
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    pad = np.zeros(int(SAMPLE_RATE * pad_seconds), dtype=np.int16)
    audio = np.concatenate([pad, audio, pad])
    usable = len(audio) - len(audio) % FRAME_SAMPLES
    return list(audio[:usable].reshape(-1, FRAME_SAMPLES))


def synthesize_speech(text: str, path: Path) -> None:
    """Record Windows' built-in voice saying `text` as a 16 kHz mono WAV."""
    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,"
        "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,"
        "[System.Speech.AudioFormat.AudioChannel]::Mono);"
        "$s.SetOutputToWaveFile($env:DRIVION_TTS_OUT, $f);"
        "$s.Speak($env:DRIVION_TTS_TEXT); $s.Dispose()"
    )
    # Text and path go through environment variables, never into the script text.
    env = {**os.environ, "DRIVION_TTS_OUT": str(path), "DRIVION_TTS_TEXT": text}
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                   check=True, env=env, timeout=60)
