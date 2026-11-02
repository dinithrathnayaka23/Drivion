"""Wake on "Hey Drivion" using the speech recognizer, with no trained model.

openWakeWord only hears phrases it has a trained model for, so this engine
listens differently: Silero VAD finds short bursts of speech, Whisper
transcribes each one, and a burst counts if it says "hey" and then the name.
Whisper has never heard "Drivion" and spells it differently each time, so
the name goes through the same fuzzy match as commands. Real voices can drift
further ("Drubian", "Tribune", "Drew Bien"), so it also counts if the
consonants sound the same: D or T, then R, then V or B, then N.

Don't pass Whisper an ``initial_prompt`` of the phrase. It looks better on
the phrase itself (30 of 30, against 27 of 30), but it then "hears" Drivion in
similar names: 9 of 40 lookalike phrases woke it, against 0 of 40 without.
See docs/WAKE_WORD.md.

A short phrase on a laptop microphone is easy to lose, so audio is judged twice:
any sound clearly above the room's background counts as well as what the VAD
calls speech, and quiet audio is boosted before it reaches the VAD and Whisper.
Whisper decides, so a false start only costs a moment of CPU.

Audio and transcripts stay in memory, and are never logged or saved.
``drivion --test-wake`` shows what is heard, on the console only.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import numpy as np

from drivion.audio.source import SAMPLE_RATE
from drivion.intents.normalize import is_assistant_name
from drivion.speech.recorder import RecorderEvent, RecorderSettings, UtteranceRecorder
from drivion.speech.stt import Transcriber
from drivion.speech.vad import VAD_FRAME_SAMPLES, SpeechProbability

GREETINGS = {"hey", "hay", "hi", "ey", "hello"}
MAX_BURST_S = 3.0  # the phrase is short; long talking is cut into pieces this size
END_SILENCE_S = 0.4
MIN_SPEECH_S = 0.12
BOOST_TARGET = 20_000  # peak level, out of 32,767
MAX_BOOST = 20.0
SILENT_PEAK = 30  # below this there's nothing worth boosting
SOUND_ABOVE_FLOOR = 4.0
MIN_SOUND_LEVEL = 40.0
FLOOR_RISE = 1.01  # per frame, so the background estimate follows a noisier room
JOIN_WITHIN_S = 1.5  # a pause after "hey" splits the phrase into two bursts
NAME_SOUND = "drvn"
_SOUND_ALIKE = str.maketrans({"t": "d", "b": "v", "f": "v"})
_NOT_THE_NAME = {"driven", "trevon"}


def sounds_like_name(words: list[str]) -> bool:
    """True if these words have the consonant pattern of "Drivion"."""
    joined = "".join(words)
    if not 5 <= len(joined) <= 10:
        return False
    sounds = re.sub(r"[aeiouwyh]", "", joined.translate(_SOUND_ALIKE))
    return re.sub(r"(.)\1+", r"\1", sounds) == NAME_SOUND


def _is_name(words: list[str]) -> bool:
    if "".join(words) in _NOT_THE_NAME:
        return False
    return is_assistant_name(words) or sounds_like_name(words)


def says_wake_phrase(text: str) -> bool:
    """True if a greeting is followed straight away by the assistant's name."""
    words = re.sub(r"[^a-z ]", " ", text.lower()).split()
    return any(
        word in GREETINGS and any(_is_name(words[i + 1:i + 1 + count]) for count in (1, 2, 3))
        for i, word in enumerate(words)
    )


def boosted(audio: np.ndarray) -> np.ndarray:
    """Quiet audio made louder, so level alone doesn't decide what gets heard."""
    peak = int(np.abs(audio.astype(np.int32)).max()) if audio.size else 0
    if peak < SILENT_PEAK or peak >= BOOST_TARGET:
        return audio
    gain = min(MAX_BOOST, BOOST_TARGET / peak)
    return np.clip(audio.astype(np.float32) * gain, -32768, 32767).astype(np.int16)


class SpokenWakeEngine:
    """A ``WakeWordEngine``: scores 1.0 at the end of a burst that says the phrase."""

    def __init__(self, vad_factory: Callable[[], SpeechProbability],
                 transcriber_factory: Callable[[], Transcriber], speech_threshold: float = 0.5,
                 on_heard: Callable[[str, bool], None] | None = None) -> None:
        self._vad_factory = vad_factory
        self._transcriber_factory = transcriber_factory
        self._vad: SpeechProbability | None = None
        self._transcriber: Transcriber | None = None
        self._on_heard = on_heard
        self._floor: float | None = None
        self._frames_seen = 0
        self._previous: tuple[str, int] | None = None  # text of the last burst, and when it ended
        self._join_frames = round(JOIN_WITHIN_S * SAMPLE_RATE / VAD_FRAME_SAMPLES)
        self._recorder = UtteranceRecorder(
            RecorderSettings(speech_threshold=speech_threshold, min_speech_s=MIN_SPEECH_S,
                             end_silence_s=END_SILENCE_S, max_utterance_s=MAX_BURST_S),
            VAD_FRAME_SAMPLES,
        )

    def reset(self) -> None:
        # The service calls this first, so the models load before listening starts.
        if self._vad is None:
            self._vad = self._vad_factory()
            self._transcriber = self._transcriber_factory()
        self._recorder.reset()
        self._previous = None

    def _is_sound(self, frame: np.ndarray) -> bool:
        """True for anything clearly louder than the room's recent background."""
        level = float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))
        self._floor = level if self._floor is None else min(level, self._floor * FLOOR_RISE)
        return level >= max(MIN_SOUND_LEVEL, self._floor * SOUND_ABOVE_FLOOR)

    def process(self, frame: np.ndarray) -> float:
        self._frames_seen += 1
        probability = 1.0 if self._is_sound(frame) else self._vad(boosted(frame))
        if self._recorder.push(frame, probability) is not RecorderEvent.FINISHED:
            return 0.0
        audio = boosted(self._recorder.utterance.audio)
        self._recorder.reset()
        text = self._transcriber.transcribe(audio).text
        earlier = ""
        if self._previous is not None and self._frames_seen - self._previous[1] <= self._join_frames:
            earlier = self._previous[0]
        self._previous = (text, self._frames_seen)
        woke = says_wake_phrase(f"{earlier} {text}")
        if self._on_heard is not None:
            self._on_heard(text, woke)
        return 1.0 if woke else 0.0
