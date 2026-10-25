"""Voice activity detection: "is someone speaking in this frame?"

Uses the Silero VAD model that ships inside faster-whisper, so no extra
download is needed. It is tiny (~0.2 ms per 64 ms frame on a laptop CPU).
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

VAD_FRAME_SAMPLES = 1_024  # 64 ms at 16 kHz; Silero needs multiples of 512


class SpeechProbability(Protocol):
    def __call__(self, frame: np.ndarray) -> float:
        """Probability (0..1) that an int16 frame contains speech."""


class SileroVad:
    def __init__(self) -> None:
        # faster-whisper's internal Silero wrapper; faster-whisper is pinned
        # exactly, so this import is stable.
        from faster_whisper.vad import get_vad_model

        self._model = get_vad_model()

    def __call__(self, frame: np.ndarray) -> float:
        samples = frame.astype(np.float32) / 32768.0
        return float(self._model(samples).max())
