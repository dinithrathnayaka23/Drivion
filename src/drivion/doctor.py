"""``drivion --doctor``: check everything Drivion needs, and say how to fix what's wrong.

It only reads: it lists devices but never opens the microphone or camera,
loads no AI provider and sends nothing over the network. See docs/RECOVERY.md.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from drivion.audio.models import BUILTIN_WAKE_WORDS, EMBEDDING, MELSPECTROGRAM, is_valid
from drivion.config import AppConfig, paths
from drivion.speech.stt import SpeechUnavailable, check_whisper_model
from drivion.vision.faces import FACE_MODELS, RECOGNIZER_ID
from drivion.vision.templates import TemplateError, TemplateStore

DOWNLOAD = "Run: drivion --download-models"
ENROLL = "Run: drivion --enroll-face"


class Status(StrEnum):
    OK = "OK"
    WARN = "WARN"    # Drivion runs, but something is limited
    FAIL = "FAIL"    # a core feature won't work


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str
    fix: str = ""


def _wake_word(config: AppConfig, models: Path) -> Check:
    settings = config.wake_word
    if not settings.enabled:
        return Check("Wake word", Status.WARN, "turned off in settings", "Open Drivion from the tray")
    needed = [MELSPECTROGRAM, EMBEDDING]
    if settings.model in BUILTIN_WAKE_WORDS:
        needed.append(BUILTIN_WAKE_WORDS[settings.model][0])
    elif not Path(settings.model).is_file():
        return Check("Wake word", Status.FAIL, f"custom model not found: {settings.model}",
                     "Fix wake_word.model in config/settings.toml")
    if not all(is_valid(models, m) for m in needed):
        return Check("Wake word", Status.FAIL, "model files missing or damaged", DOWNLOAD)
    return Check("Wake word", Status.OK, f"model {settings.model}")


def _speech(config: AppConfig, models: Path) -> Check:
    if not config.voice.enabled:
        return Check("Speech recognition", Status.WARN, "turned off in settings", "")
    try:
        check_whisper_model(models, config.voice.stt_model)
    except SpeechUnavailable:
        return Check("Speech recognition", Status.FAIL, f"model {config.voice.stt_model} missing", DOWNLOAD)
    return Check("Speech recognition", Status.OK, f"model {config.voice.stt_model}")


def _face_models(models: Path) -> Check:
    if all(is_valid(models, m) for m in FACE_MODELS):
        return Check("Face models", Status.OK, "YuNet and SFace verified")
    return Check("Face models", Status.FAIL, "missing or damaged", DOWNLOAD)


def _enrollment(store: TemplateStore) -> Check:
    if not store.exists():
        return Check("Face enrollment", Status.FAIL, "no face enrolled, so Drivion can't unlock", ENROLL)
    try:
        templates = store.load(RECOGNIZER_ID)
    except TemplateError as exc:
        return Check("Face enrollment", Status.FAIL, str(exc), ENROLL)
    return Check("Face enrollment", Status.OK, f"{len(templates.embeddings)} templates, encrypted")


def _liveness(config: AppConfig) -> Check:
    if config.face.liveness_mode == "none":
        return Check("Liveness check", Status.WARN, "off: a photo of you could unlock Drivion",
                     'Set face.liveness_mode = "challenge"')
    return Check("Liveness check", Status.OK, f"{config.face.liveness_challenges} random head turns")


def _ai(config: AppConfig, secrets) -> Check:
    if not config.llm.enabled:
        return Check("AI providers", Status.OK, "turned off (offline commands only)")
    with_keys = [p for p in config.llm.providers if secrets.key_for(p) is not None]
    if not with_keys:
        return Check("AI providers", Status.WARN, "no API key set, so questions can't be answered",
                     "Add a key to .env (see docs/AI.md)")
    return Check("AI providers", Status.OK, f"keys set: {', '.join(with_keys)} (not tested)")


def _microphone() -> Check:
    from drivion.audio.source import list_input_devices

    try:
        devices = list_input_devices()
    except Exception as exc:
        return Check("Microphone", Status.FAIL, f"audio system error: {exc}",
                     "Check Windows sound settings")
    if not devices:
        return Check("Microphone", Status.FAIL, "no microphone found",
                     "Connect one, and check Settings > Privacy & security > Microphone")
    default = next((name for _, name, _, is_default in devices if is_default), devices[0][1])
    return Check("Microphone", Status.OK, f"found (default: {default}; not opened)")


def _voices(config: AppConfig) -> Check:
    if config.voice.tts_engine == "none":
        return Check("Spoken replies", Status.OK, "turned off (replies are shown only)")
    from drivion.speech.tts import installed_voices

    try:
        voices = installed_voices()
    except Exception as exc:
        return Check("Spoken replies", Status.WARN, f"Windows speech is unavailable: {exc}",
                     "Check Settings > Time & language > Speech")
    if not voices:
        return Check("Spoken replies", Status.WARN, "no Windows voices installed",
                     "Add a voice in Settings > Time & language > Speech")
    return Check("Spoken replies", Status.OK, f"{len(voices)} Windows voices")


def run_checks(config: AppConfig, secrets, *, hardware: bool = True,
               store: TemplateStore | None = None, models: Path | None = None) -> list[Check]:
    models = models or paths.models_dir()
    store = store or TemplateStore(paths.face_dir())
    checks = [
        _wake_word(config, models), _speech(config, models), _face_models(models),
        _enrollment(store), _liveness(config), _ai(config, secrets),
    ]
    if hardware:
        checks += [_microphone(), _voices(config)]
    return checks


def print_report(checks: list[Check], write: Callable[[str], None] = print) -> bool:
    """Print the report. Returns False if a core feature won't work."""
    for check in checks:
        write(f"[{check.status.value:<4}] {check.name}: {check.detail}")
        if check.fix and check.status is not Status.OK:
            write(f"       Fix: {check.fix}")
    failed = sum(c.status is Status.FAIL for c in checks)
    write("")
    write(f"{failed} problem(s) to fix." if failed else "Everything Drivion needs is in place.")
    write("The camera wasn't opened; to try it, run: drivion --test-face")
    sys.stdout.flush()
    return failed == 0
