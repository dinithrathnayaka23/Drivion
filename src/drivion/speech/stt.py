"""Speech-to-text with faster-whisper, running locally on the CPU.

Models are downloaded only by ``drivion --download-models``, from a pinned
Hugging Face revision, into ``%LOCALAPPDATA%\\Drivion\\models\\whisper``. At
runtime the model is loaded from that folder, so recognition works offline
and audio never leaves the computer.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)

# Model name -> (Hugging Face repository, pinned commit). Pinning the commit
# means a changed upstream repository can't silently change what we load.
WHISPER_MODELS: dict[str, tuple[str, str]] = {
    "tiny.en": ("Systran/faster-whisper-tiny.en", "0d3d19a32d3338f10357c0889762bd8d64bbdeba"),
    "base.en": ("Systran/faster-whisper-base.en", "3d3d5dee26484f91867d81cb899cfcf72b96be6c"),
    "small.en": ("Systran/faster-whisper-small.en", "d1d751a5f8271d482d14ca55d9e2deeebbae577f"),
}
_REQUIRED_FILES = ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")

# Whisper tends to "hear" words like "you" or "Thank you." in silence or noise.
# Segments it itself rates as probably-not-speech are discarded.
NO_SPEECH_THRESHOLD = 0.6


class SpeechUnavailable(Exception):
    """The speech-recognition model is missing or can't be loaded."""


@dataclass(frozen=True)
class Transcript:
    text: str
    seconds: float  # time spent transcribing


class Transcriber(Protocol):
    def transcribe(self, audio: np.ndarray) -> Transcript:
        """Transcribe 16 kHz int16 audio. Empty text means nothing usable was heard."""


def whisper_model_dir(models_dir: Path, name: str) -> Path:
    return models_dir / "whisper" / name


def check_whisper_model(models_dir: Path, name: str) -> Path:
    directory = whisper_model_dir(models_dir, name)
    missing = [f for f in _REQUIRED_FILES if not (directory / f).is_file()]
    if missing:
        raise SpeechUnavailable(
            f"Speech model {name!r} is not downloaded (missing {', '.join(missing)}). "
            "Run `drivion --download-models`."
        )
    return directory


def download_whisper_model(models_dir: Path, name: str) -> Path:
    from faster_whisper.utils import download_model

    repo, revision = WHISPER_MODELS[name]
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    target = whisper_model_dir(models_dir, name)
    log.info("Downloading %s at revision %s", repo, revision[:12])
    download_model(repo, output_dir=str(target), revision=revision)
    return check_whisper_model(models_dir, name)


_ONLY_PUNCTUATION = re.compile(r"^[\W_]*$")


def clean_text(segments) -> str:
    """Join usable segments, dropping ones Whisper marks as likely non-speech."""
    kept = [s.text.strip() for s in segments if s.no_speech_prob <= NO_SPEECH_THRESHOLD]
    text = " ".join(t for t in kept if t)
    return "" if _ONLY_PUNCTUATION.match(text) else text


class WhisperTranscriber:
    def __init__(self, model_dir: Path, threads: int = 0) -> None:
        try:
            from faster_whisper import WhisperModel

            started = time.perf_counter()
            self._model = WhisperModel(
                str(model_dir), device="cpu", compute_type="int8", cpu_threads=threads,
            )
        except Exception as exc:
            raise SpeechUnavailable(f"Could not load speech model from {model_dir}: {exc}") from exc
        log.info("Speech model loaded from %s in %.2fs", model_dir.name, time.perf_counter() - started)

    def transcribe(self, audio: np.ndarray) -> Transcript:
        started = time.perf_counter()
        segments, _ = self._model.transcribe(
            audio.astype(np.float32) / 32768.0,
            language="en",
            beam_size=1,                      # greedy: fastest, accurate enough for commands
            vad_filter=False,                 # we already cut out the speech ourselves
            condition_on_previous_text=False, # each command stands alone
        )
        text = clean_text(list(segments))
        return Transcript(text, time.perf_counter() - started)
