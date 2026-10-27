"""Validated, non-secret application configuration.

Settings come from three layers, later layers winning:
1. Defaults defined on the models below.
2. An optional TOML file (``config/settings.toml`` by default).
3. Nothing else - secrets are handled separately in ``secrets.py``.

Every model forbids unknown keys, so a typo such as ``sensitivty = 0.7``
fails loudly at startup instead of being silently ignored.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


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


_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class AppEntry(_Section):
    """One allowlisted app."""

    # Extra spoken names (the id itself, with "_" as spaces, always works).
    aliases: list[str] = []
    # What Windows should open: an App Paths name ("chrome.exe"), a program on
    # PATH ("notepad.exe") or a full path. No arguments are ever passed.
    launch: str | None = Field(default=None, min_length=1)
    # Executable name of its windows, for minimize/restore (e.g. "chrome.exe").
    process: str | None = Field(default=None, min_length=1)

    @field_validator("launch")
    @classmethod
    def _no_arguments(cls, value: str | None) -> str | None:
        # Defence in depth: Windows treats the whole string as one file name anyway,
        # but anything that looks like arguments or shell syntax is refused outright.
        if value is not None and (
            any(ch in value for ch in '"&|<>^*?%') or re.search(r"\s[/-]", value)
        ):
            raise ValueError("must be a program name or path, without arguments or shell symbols")
        return value


class CommandsSettings(_Section):
    """The allowlist: only these apps, websites and folders can be opened by voice.

    A section you set in your config replaces the defaults below entirely.
    """

    apps: dict[str, AppEntry] = {
        "chrome": AppEntry(aliases=["google chrome", "browser", "web browser"],
                           launch="chrome.exe", process="chrome.exe"),
        "vscode": AppEntry(aliases=["vs code", "visual studio code", "code editor"],
                           launch="Code.exe", process="Code.exe"),
        "explorer": AppEntry(aliases=["file explorer", "windows explorer", "files"],
                             launch="explorer.exe", process="explorer.exe"),
        "notepad": AppEntry(launch="notepad.exe", process="Notepad.exe"),
        "calculator": AppEntry(aliases=["calc"], launch="calc.exe", process="CalculatorApp.exe"),
    }
    websites: dict[str, str] = {
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "github": "https://github.com",
        "gmail": "https://mail.google.com",
    }
    folders: dict[str, str] = {
        "downloads": "~/Downloads",
        "documents": "~/Documents",
        "desktop": "~/Desktop",
        "pictures": "~/Pictures",
    }

    @field_validator("apps", mode="before")
    @classmethod
    def _aliases_list_shorthand(cls, value):
        # Milestone 6 format, still accepted: `chrome = ["browser"]` (aliases only).
        if isinstance(value, dict):
            return {k: {"aliases": v} if isinstance(v, list) else v for k, v in value.items()}
        return value

    @field_validator("apps", "websites", "folders")
    @classmethod
    def _ids_are_simple(cls, value: dict) -> dict:
        for key in value:
            if not _ID.match(key):
                raise ValueError(f"{key!r}: ids must be lowercase letters, digits or _")
        return value

    @field_validator("websites")
    @classmethod
    def _https_only(cls, value: dict[str, str]) -> dict[str, str]:
        for name, url in value.items():
            if not url.startswith("https://") or " " in url:
                raise ValueError(f"{name!r}: website must be an https:// address")
        return value

    @model_validator(mode="after")
    def _no_ambiguous_names(self) -> "CommandsSettings":
        from drivion.intents.catalog import Catalog

        Catalog.from_settings(self)  # raises on a name used twice
        return self

    @property
    def app_aliases(self) -> dict[str, list[str]]:
        return {app_id: entry.aliases for app_id, entry in self.apps.items()}


class ActionsSettings(_Section):
    """How Windows actions behave (see docs/ACTIONS.md)."""

    screenshot_dir: str = "~/Pictures/Screenshots"
    # High-risk actions (sleep, restart, shut down) wait this long for "yes".
    confirmation_timeout_s: float = Field(default=15.0, ge=5.0, le=60.0)
    # Restart and shutdown happen after this delay; saying "cancel" aborts them.
    power_delay_s: int = Field(default=10, ge=5, le=120)
    # "sleep" asks Windows to sleep (may be refused on Modern Standby laptops);
    # "hibernate" saves your session to disk and powers off.
    sleep_method: Literal["sleep", "hibernate"] = "sleep"


class AppConfig(_Section):
    general: GeneralSettings = GeneralSettings()
    ui: UISettings = UISettings()
    wake_word: WakeWordSettings = WakeWordSettings()
    face: FaceSettings = FaceSettings()
    voice: VoiceSettings = VoiceSettings()
    commands: CommandsSettings = CommandsSettings()
    actions: ActionsSettings = ActionsSettings()
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
