"""Cuts one spoken command out of a continuous stream of audio frames.

    WAITING ──(speech for min_speech_s)──► SPEAKING ──(silence for end_silence_s,
       ▲                                      │        or max_utterance_s reached)
       └────────────── reset() ◄──────────────┴──► Finished(audio)

A short "pre-roll" of audio from before speech was detected is kept, so
the first syllable isn't cut off. This class is pure logic: it doesn't
touch the microphone or the models, which makes it easy to test.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from enum import Enum

import numpy as np

from drivion.audio.source import SAMPLE_RATE


@dataclass(frozen=True)
class RecorderSettings:
    speech_threshold: float = 0.5
    min_speech_s: float = 0.2      # ignore clicks and coughs shorter than this
    end_silence_s: float = 0.8     # this much silence ends the command
    max_utterance_s: float = 15.0  # hard cap, so a noisy room can't record forever
    pre_roll_s: float = 0.3


class RecorderEvent(Enum):
    STARTED = "STARTED"
    FINISHED = "FINISHED"


@dataclass(frozen=True)
class Utterance:
    audio: np.ndarray  # int16 samples
    truncated: bool    # True if max_utterance_s cut it off

    @property
    def duration_s(self) -> float:
        return len(self.audio) / SAMPLE_RATE


class UtteranceRecorder:
    def __init__(self, settings: RecorderSettings, frame_samples: int) -> None:
        self.settings = settings
        frame_s = frame_samples / SAMPLE_RATE
        self._min_speech_frames = max(1, math.ceil(settings.min_speech_s / frame_s))
        self._end_silence_frames = max(1, math.ceil(settings.end_silence_s / frame_s))
        self._max_frames = max(1, math.ceil(settings.max_utterance_s / frame_s))
        pre_roll_frames = math.ceil(settings.pre_roll_s / frame_s)
        self._pre_roll: deque[np.ndarray] = deque(maxlen=pre_roll_frames + self._min_speech_frames)
        self.utterance: Utterance | None = None
        self.reset()

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def reset(self) -> None:
        self._speaking = False
        self._speech_run = 0
        self._silence_run = 0
        self._frames: list[np.ndarray] = []
        self._pre_roll.clear()
        self.utterance = None

    def push(self, frame: np.ndarray, speech_probability: float) -> RecorderEvent | None:
        if self.utterance is not None:
            # A finished command is waiting to be collected; never overwrite it.
            # The caller takes `utterance` and calls reset() before the next one.
            return None
        is_speech = speech_probability >= self.settings.speech_threshold
        if not self._speaking:
            self._pre_roll.append(frame)
            self._speech_run = self._speech_run + 1 if is_speech else 0
            if self._speech_run >= self._min_speech_frames:
                self._speaking = True
                self._frames = list(self._pre_roll)
                self._silence_run = 0
                return RecorderEvent.STARTED
            return None

        self._frames.append(frame)
        self._silence_run = 0 if is_speech else self._silence_run + 1
        ended_by_silence = self._silence_run >= self._end_silence_frames
        if ended_by_silence or len(self._frames) >= self._max_frames:
            self.utterance = Utterance(np.concatenate(self._frames), truncated=not ended_by_silence)
            self._speaking = False
            return RecorderEvent.FINISHED
        return None
