"""Audio input: the microphone, behind a small interface tests can fake.

Every source delivers 16 kHz, mono, 16-bit frames of a fixed length,
which is the format both the wake-word engine and (later) speech
recognition expect.
"""

from __future__ import annotations

import logging
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 1_280  # 80 ms, the frame size openWakeWord is designed for


class AudioDeviceError(Exception):
    """The microphone is missing, busy, blocked by privacy settings, or failed."""


class AudioSource(Protocol):
    def open(self) -> None: ...

    def read(self) -> np.ndarray | None:
        """Block for up to about one frame; return int16 samples, or None at end of input."""

    def close(self) -> None: ...


class MicrophoneSource:
    """Reads the microphone with PortAudio (via sounddevice)."""

    def __init__(self, device: int | str | None = None, frame_samples: int = FRAME_SAMPLES) -> None:
        self.device = device
        self.frame_samples = frame_samples
        self._stream = None
        self._overflows = 0

    def open(self) -> None:
        import sounddevice as sd  # imported lazily: loading PortAudio isn't free

        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                blocksize=self.frame_samples, device=self.device,
            )
            self._stream.start()
        except Exception as exc:  # PortAudioError, ValueError for a bad device name, ...
            self._stream = None
            raise AudioDeviceError(f"Could not open microphone {self.device or '(default)'}: {exc}") from exc
        log.info("Microphone opened (%s)", self._stream.device)

    def read(self) -> np.ndarray | None:
        if self._stream is None:
            raise AudioDeviceError("Microphone is not open")
        try:
            data, overflowed = self._stream.read(self.frame_samples)
        except Exception as exc:
            raise AudioDeviceError(f"Microphone read failed: {exc}") from exc
        if overflowed:
            # Samples were dropped because processing fell behind. Rare; harmless
            # for wake-word detection, but worth knowing about when tuning.
            self._overflows += 1
            log.debug("Microphone input overflow (%d so far)", self._overflows)
        return data[:, 0].copy()

    def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                log.exception("Error while closing the microphone")
            log.info("Microphone closed")


def list_input_devices() -> list[tuple[int, str, str, bool]]:
    """(index, name, audio system, is_default) for every device that can record.

    Windows lists the same microphone once per audio system (MME,
    DirectSound, WASAPI, WDM-KS), which is why names repeat.
    """
    import sounddevice as sd

    default_input = sd.default.device[0]
    host_apis = sd.query_hostapis()
    return [
        (index, device["name"], host_apis[device["hostapi"]]["name"], index == default_input)
        for index, device in enumerate(sd.query_devices())
        if device["max_input_channels"] > 0
    ]
