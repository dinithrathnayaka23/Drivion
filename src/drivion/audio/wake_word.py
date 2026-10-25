"""Wake-word detection.

Three pieces, each with one job:

* ``WakeWordEngine`` - turns an audio frame into a score (0..1). The only
  implementation today is openWakeWord; a Porcupine adapter could be added
  behind the same interface.
* ``WakeWordDetector`` - decides when a score counts as a detection
  (threshold) and suppresses repeats from the same utterance (cooldown).
* ``WakeWordService`` - a background thread that reads the microphone,
  feeds the engine and reports detections and the microphone's real state.

Wake-word detection is deliberately separate from speech recognition: this
small model runs continuously in standby, while full transcription only
runs after activation.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import numpy as np

from drivion.audio.models import (
    BUILTIN_WAKE_WORDS,
    EMBEDDING,
    MELSPECTROGRAM,
    ModelFile,
    is_valid,
)
from drivion.audio.source import AudioDeviceError, AudioSource
from drivion.core.activity import DeviceState
from drivion.core.services import CrashHandler, ThreadedService

log = logging.getLogger(__name__)

DEFAULT_PHRASE = "Wake up, Drivion"


class WakeWordUnavailable(Exception):
    """The engine can't be built (models missing, invalid or unloadable)."""


class WakeWordEngine(Protocol):
    def process(self, frame: np.ndarray) -> float:
        """Score one 80 ms int16 frame; higher means more likely the wake word."""

    def reset(self) -> None:
        """Forget buffered audio (after a detection or when listening restarts)."""


def sensitivity_to_threshold(sensitivity: float) -> float:
    """Map the user-facing sensitivity (0..1, higher = triggers more easily)
    to the engine's score threshold. 0.5 gives openWakeWord's default 0.5."""
    return min(0.95, max(0.05, 1.0 - sensitivity))


class OpenWakeWordEngine:
    def __init__(self, model_path: Path, models_dir: Path) -> None:
        try:
            from openwakeword.model import Model

            self._model = Model(
                wakeword_models=[str(model_path)],
                inference_framework="onnx",
                melspec_model_path=str(models_dir / MELSPECTROGRAM.filename),
                embedding_model_path=str(models_dir / EMBEDDING.filename),
            )
        except Exception as exc:
            raise WakeWordUnavailable(f"openWakeWord could not load {model_path.name}: {exc}") from exc

    def process(self, frame: np.ndarray) -> float:
        scores = self._model.predict(frame)
        return float(max(scores.values()))

    def reset(self) -> None:
        self._model.reset()


def resolve_wake_word(model: str, models_dir: Path, phrase: str | None) -> tuple[Path, str]:
    """Turn the configured model (built-in name or .onnx path) into a file and display phrase."""
    required: list[ModelFile] = [MELSPECTROGRAM, EMBEDDING]
    if model in BUILTIN_WAKE_WORDS:
        model_file, builtin_phrase = BUILTIN_WAKE_WORDS[model]
        required.append(model_file)
        path, display = models_dir / model_file.filename, phrase or builtin_phrase
    else:
        path, display = Path(model), phrase or DEFAULT_PHRASE
        if not path.is_file():
            raise WakeWordUnavailable(f"Custom wake-word model not found: {path}")

    broken = [m.filename for m in required if not is_valid(models_dir, m)]
    if broken:
        raise WakeWordUnavailable(
            f"Missing or invalid model files: {', '.join(broken)}. "
            "Run `drivion --download-models`."
        )
    return path, display


class WakeWordDetector:
    def __init__(self, threshold: float, cooldown_s: float,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self._clock = clock
        self._last_detection: float | None = None

    def update(self, score: float) -> bool:
        if score < self.threshold:
            return False
        now = self._clock()
        if self._last_detection is not None and now - self._last_detection < self.cooldown_s:
            return False  # the same utterance scores high for several frames
        self._last_detection = now
        return True


class WakeWordService(ThreadedService):
    """Listens in a background thread; the microphone is open only while running."""

    def __init__(
        self,
        source_factory: Callable[[], AudioSource],
        engine: WakeWordEngine,
        detector: WakeWordDetector,
        on_detected: Callable[[float], None],
        on_microphone: Callable[[DeviceState], None],
        on_crash: CrashHandler | None = None,
    ) -> None:
        super().__init__("wake-word", on_crash=on_crash)
        self._source_factory = source_factory
        self._engine = engine
        self._detector = detector
        self._on_detected = on_detected
        self._on_microphone = on_microphone
        self._source: AudioSource | None = None
        self._mic_failed = False

    def run(self, stop_event: threading.Event) -> None:
        self._mic_failed = False
        self._engine.reset()
        self._source = self._source_factory()
        try:
            self._source.open()
        except AudioDeviceError:
            self._mic_failed = True
            raise
        self._on_microphone(DeviceState.ACTIVE)
        log.info("Wake-word listening started (threshold %.2f)", self._detector.threshold)

        while not stop_event.is_set():
            try:
                frame = self._source.read()
            except AudioDeviceError:
                self._mic_failed = True
                raise
            if frame is None:  # end of input (only finite test sources end)
                break
            score = self._engine.process(frame)
            if self._detector.update(score):
                log.info("Wake word detected (score %.2f)", score)
                self._engine.reset()
                self._on_detected(score)

    def cleanup(self) -> None:
        if self._source is not None:
            self._source.close()
            self._source = None
        # Report the real state: the device is closed now, or it failed.
        self._on_microphone(DeviceState.ERROR if self._mic_failed else DeviceState.OFF)
        log.info("Wake-word listening stopped")
