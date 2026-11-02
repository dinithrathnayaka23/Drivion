"""Wake on "Hey Drivion" using the speech recognizer, with no trained model.

openWakeWord only hears phrases it has a trained model for, so this engine
listens differently: Silero VAD finds short bursts of speech, Whisper
transcribes each one, and a burst counts if it says "hey" and then the name.
Whisper has never heard "Drivion" and spells it differently each time, so
the name goes through the same fuzzy match as commands.

Don't pass Whisper an ``initial_prompt`` of the phrase. It looks better on
the phrase itself (30 of 30, against 27 of 30), but it then "hears" Drivion in
similar names: 9 of 40 lookalike phrases woke it, against 0 of 40 without.
See docs/WAKE_WORD.md.

Audio and transcripts stay in memory, and are never logged or saved.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import numpy as np

from drivion.intents.normalize import is_assistant_name
from drivion.speech.recorder import RecorderEvent, RecorderSettings, UtteranceRecorder
from drivion.speech.stt import Transcriber
from drivion.speech.vad import VAD_FRAME_SAMPLES, SpeechProbability

GREETINGS = {"hey", "hay", "hi", "ey"}
MAX_BURST_S = 3.0  # the phrase is short; long talking is cut into pieces this size
END_SILENCE_S = 0.4


def says_wake_phrase(text: str) -> bool:
    """True if a greeting is followed straight away by the assistant's name."""
    words = re.sub(r"[^a-z ]", " ", text.lower()).split()
    return any(
        word in GREETINGS and any(is_assistant_name(words[i + 1:i + 1 + count]) for count in (1, 2))
        for i, word in enumerate(words)
    )


class SpokenWakeEngine:
    """A ``WakeWordEngine``: scores 1.0 at the end of a burst that says the phrase."""

    def __init__(self, vad_factory: Callable[[], SpeechProbability],
                 transcriber_factory: Callable[[], Transcriber], speech_threshold: float = 0.5) -> None:
        self._vad_factory = vad_factory
        self._transcriber_factory = transcriber_factory
        self._vad: SpeechProbability | None = None
        self._transcriber: Transcriber | None = None
        self._recorder = UtteranceRecorder(
            RecorderSettings(speech_threshold=speech_threshold, end_silence_s=END_SILENCE_S,
                             max_utterance_s=MAX_BURST_S),
            VAD_FRAME_SAMPLES,
        )

    def reset(self) -> None:
        # The service calls this first, so the models load before listening starts.
        if self._vad is None:
            self._vad = self._vad_factory()
            self._transcriber = self._transcriber_factory()
        self._recorder.reset()

    def process(self, frame: np.ndarray) -> float:
        if self._recorder.push(frame, self._vad(frame)) is not RecorderEvent.FINISHED:
            return 0.0
        audio = self._recorder.utterance.audio
        self._recorder.reset()
        return 1.0 if says_wake_phrase(self._transcriber.transcribe(audio).text) else 0.0
