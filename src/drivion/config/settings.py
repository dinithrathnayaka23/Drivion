"""Validated, non-secret application configuration.

Settings come from three layers, later layers winning:
1. Defaults defined on the models below.
2. An optional TOML file (``config/settings.toml`` by default).
3. Nothing else - secrets are handled separately in ``secrets.py``.

Every model forbids unknown keys, so a typo such as ``sensitivty = 0.7``
fails loudly at startup instead of being silently ignored.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class ConfigError(Exception):
    """Raised when the configuration file is missing required structure or is invalid."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GeneralSettings(_Section):
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class UISettings(_Section):
    animations: bool = True  # False = static indicator (reduced motion, lower CPU)
    history_limit: int = Field(default=50, ge=10, le=500)


class WakeWordSettings(_Section):
    enabled: bool = True
    engine: Literal["openwakeword"] = "openwakeword"
    # A built-in model name ("hey_jarvis") or the path to a custom .onnx model.
    model: str = Field(default="hey_jarvis", min_length=1)
    # Phrase shown in the dashboard; defaults to the built-in model's phrase.
    phrase: str | None = None
    sensitivity: float = Field(default=0.5, ge=0.0, le=1.0)
    # Ignore repeat detections for this long (one utterance scores on many frames).
    cooldown_s: float = Field(default=2.0, ge=0.5, le=10.0)
    # Microphone index or (part of) its name; omit to use the Windows default.
    input_device: int | str | None = None

    @field_validator("model")
    @classmethod
    def _builtin_or_onnx(cls, value: str) -> str:
        from drivion.audio.models import BUILTIN_WAKE_WORDS

        if value not in BUILTIN_WAKE_WORDS and not value.lower().endswith(".onnx"):
            known = ", ".join(sorted(BUILTIN_WAKE_WORDS))
            raise ValueError(f"must be a built-in model ({known}) or a path to a .onnx file")
        return value


class FaceSettings(_Section):
    similarity_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    store_raw_images: bool = False
    liveness_mode: Literal["none", "blink", "challenge"] = "challenge"
    # How long to wait for a verification result before failing closed.
    verification_timeout_s: float = Field(default=10.0, ge=1.0, le=60.0)


class VoiceSettings(_Section):
    # Speech input (recognition) while ACTIVE.
    enabled: bool = True
    stt_model: Literal["tiny.en", "base.en", "small.en"] = "base.en"
    stt_threads: int = Field(default=0, ge=0, le=16)  # 0 = let faster-whisper decide
    speech_threshold: float = Field(default=0.5, ge=0.1, le=0.9)
    end_silence_s: float = Field(default=0.8, ge=0.3, le=3.0)
    max_command_s: float = Field(default=15.0, ge=3.0, le=60.0)
    # No speech for this long while ACTIVE -> back to standby.
    command_timeout_s: float = Field(default=20.0, ge=3.0, le=300.0)
    # Speech output (Windows voices).
    tts_engine: Literal["windows", "none"] = "windows"
    tts_voice: str | None = None  # part of a voice name, e.g. "Zira"; omit for default
    tts_rate: int = Field(default=0, ge=-10, le=10)
    tts_volume: int = Field(default=100, ge=0, le=100)
    greeting: str = "I'm listening."  # spoken on activation; "" to stay quiet


class LLMSettings(_Section):
    provider: Literal["none", "openai", "anthropic"] = "none"
    model: str = ""
    request_timeout_s: float = Field(default=20.0, gt=0.0, le=120.0)


class AppConfig(_Section):
    general: GeneralSettings = GeneralSettings()
    ui: UISettings = UISettings()
    wake_word: WakeWordSettings = WakeWordSettings()
    face: FaceSettings = FaceSettings()
    voice: VoiceSettings = VoiceSettings()
    llm: LLMSettings = LLMSettings()


def load_config(path: Path | None) -> AppConfig:
    """Load and validate configuration.

    A missing file is not an error (defaults are used); a malformed or
    invalid file is, because silently falling back could hide a mistake in
    a security-relevant setting such as the face similarity threshold.
    """
    if path is None or not path.exists():
        return AppConfig()

    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: not valid TOML ({exc})") from exc

    try:
        return AppConfig.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise ConfigError(f"{path}: {problems}") from exc
