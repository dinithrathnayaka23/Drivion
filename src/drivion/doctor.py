"""``drivion --doctor``: check everything Drivion needs, and say how to fix what's wrong.

It only reads: it lists devices but never opens the microphone or camera,
loads no AI provider and sends nothing over the network. See docs/RECOVERY.md.

``drivion --self-test`` goes further: it loads every model and library and runs
them on silence and a blank picture. It is how a packaged build shows that
nothing was left out. It also never opens the microphone or camera.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import numpy as np

from drivion.audio.models import BUILTIN_WAKE_WORDS, EMBEDDING, MELSPECTROGRAM, is_valid
from drivion.audio.wake_word import DEFAULT_PHRASE
from drivion.config import AppConfig, paths
from drivion.core.autostart import Autostart
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
    if settings.engine == "whisper":
        try:
            check_whisper_model(models, config.voice.stt_model)
        except SpeechUnavailable:
            return Check("Wake word", Status.FAIL, f"speech model {config.voice.stt_model} missing", DOWNLOAD)
        return Check("Wake word", Status.OK, f"{settings.phrase or DEFAULT_PHRASE!r} (speech model)")
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


def _start_at_login(autostart: Autostart) -> Check:
    if not autostart.is_enabled():
        return Check("Start at login", Status.OK, "off")
    if not autostart.is_current():
        return Check("Start at login", Status.WARN, "points to an old location",
                     "Run: drivion --autostart on")
    return Check("Start at login", Status.OK, "on")


def run_checks(config: AppConfig, secrets, *, hardware: bool = True,
               store: TemplateStore | None = None, models: Path | None = None) -> list[Check]:
    models = models or paths.models_dir()
    store = store or TemplateStore(paths.face_dir())
    checks = [
        _wake_word(config, models), _speech(config, models), _face_models(models),
        _enrollment(store), _liveness(config), _ai(config, secrets),
    ]
    if hardware:
        checks += [_microphone(), _voices(config), _start_at_login(Autostart())]
    return checks


def _try_wake_word(config: AppConfig, models: Path) -> str:
    from drivion.audio.spoken_wake import SpokenWakeEngine
    from drivion.audio.wake_word import OpenWakeWordEngine, resolve_wake_word
    from drivion.speech.stt import WhisperTranscriber
    from drivion.speech.vad import VAD_FRAME_SAMPLES, SileroVad

    if config.wake_word.engine == "whisper":
        model = check_whisper_model(models, config.voice.stt_model)
        engine = SpokenWakeEngine(SileroVad, lambda: WhisperTranscriber(model, config.voice.stt_threads))
        engine.reset()
        engine.process(np.zeros(VAD_FRAME_SAMPLES, dtype=np.int16))
        return f"{config.wake_word.phrase or DEFAULT_PHRASE!r} engine ran"
    model_path, phrase = resolve_wake_word(config.wake_word.model, models, config.wake_word.phrase)
    OpenWakeWordEngine(model_path, models).process(np.zeros(1_280, dtype=np.int16))
    return f"{phrase!r} model ran"


def _try_voice_activity(config: AppConfig, models: Path) -> str:
    from drivion.speech.vad import VAD_FRAME_SAMPLES, SileroVad

    SileroVad()(np.zeros(VAD_FRAME_SAMPLES, dtype=np.int16))
    return "Silero model ran"


def _try_speech(config: AppConfig, models: Path) -> str:
    from drivion.speech.stt import WhisperTranscriber

    model = check_whisper_model(models, config.voice.stt_model)
    WhisperTranscriber(model, config.voice.stt_threads).transcribe(np.zeros(16_000, dtype=np.int16))
    return f"{config.voice.stt_model} transcribed silence"


def _try_face(config: AppConfig, models: Path) -> str:
    from drivion.vision.faces import OpenCVFaceAnalyzer
    from drivion.vision.quality import Face

    analyzer = OpenCVFaceAnalyzer(models)
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    analyzer.detect(frame)
    # A blank picture has no face, so give SFace made-up landmarks.
    raw = np.float32([60, 60, 100, 100, 90, 100, 130, 100, 110, 120, 95, 140, 125, 140, 0.9])
    size = analyzer.embed(frame, Face((60, 60, 100, 100), raw[4:14].reshape(5, 2), 0.9, raw)).size
    return f"YuNet and SFace ran ({size} numbers)"


def _try_windows_voice(config: AppConfig, models: Path) -> str:
    from drivion.speech.tts import installed_voices

    return f"{len(installed_voices())} voices found"


def _try_installed_apps(config: AppConfig, models: Path) -> str:
    from drivion.actions.windows.start_apps import list_start_apps
    from drivion.intents.installed import InstalledApps

    return f"{len(InstalledApps(list_start_apps))} apps can be opened by voice"


def _try_radios(config: AppConfig, models: Path) -> str:
    from drivion.actions.windows.radios import RadioUnavailable, WindowsRadios

    states = []
    for radio in ("bluetooth", "wifi"):
        try:
            states.append(f"{radio} {'on' if WindowsRadios().is_on(radio) else 'off'}")
        except RadioUnavailable:
            states.append(f"no {radio}")
    return ", ".join(states)


def _try_window_list(config: AppConfig, models: Path) -> str:
    from drivion.actions.windows.desktop import WindowsDesktop

    return f"{len(WindowsDesktop().list_windows())} open windows found"


def _try_volume(config: AppConfig, models: Path) -> str:
    from drivion.actions.windows.audio import PycawVolume

    return f"read the level: {PycawVolume().get_percent()}%"


def _try_https(config: AppConfig, models: Path) -> str:
    import ssl

    return f"{len(ssl.create_default_context().get_ca_certs())} trusted certificates (nothing sent)"


def _try_dashboard(config: AppConfig, models: Path) -> str:
    from PySide6.QtWidgets import QApplication

    from drivion.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    MainWindow(animated=False).deleteLater()  # built, never shown
    app.processEvents()
    return "built"


SELF_TESTS = {
    "Wake word engine": _try_wake_word, "Voice activity": _try_voice_activity,
    "Speech recognition": _try_speech, "Face engine": _try_face,
    "Windows voices": _try_windows_voice, "Installed apps": _try_installed_apps,
    "Bluetooth and Wi-Fi": _try_radios, "Open windows": _try_window_list,
    "Volume control": _try_volume,
    "HTTPS": _try_https, "Dashboard": _try_dashboard,
}


def run_self_test(config: AppConfig, models: Path | None = None) -> list[Check]:
    models = models or paths.models_dir()
    checks = []
    for name, attempt in SELF_TESTS.items():
        try:
            checks.append(Check(name, Status.OK, attempt(config, models)))
        except Exception as exc:  # the whole point is to report these, not stop at the first
            checks.append(Check(name, Status.FAIL, f"{type(exc).__name__}: {exc}"))
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
