"""Application entry point and composition root.

Startup order matters:
1. Parse arguments.
2. Load secrets, then config (fail fast on invalid config, before any UI).
3. Configure logging with the secrets registered for redaction.
4. Either print a config report (--check-config) or:
5. Take the single-instance lock (or ask the running Drivion to open, then exit).
6. Build controller, window, tray and activation server, then run the Qt event loop.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from collections.abc import Sequence
from pathlib import Path

from drivion import __version__
from drivion.config import AppConfig, ConfigError, load_config, load_secrets
from drivion.config import paths
from drivion.logging_setup import configure_logging

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CONFIG_ERROR = 2
EXIT_ALREADY_RUNNING = 3


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="drivion", description="Drivion desktop assistant")
    parser.add_argument(
        "--config", type=Path, default=paths.DEFAULT_CONFIG_FILE,
        help="path to settings TOML (default: config/settings.toml)",
    )
    parser.add_argument(
        "--env-file", type=Path, default=paths.DEFAULT_ENV_FILE,
        help="path to the secrets .env file (default: .env in the project root)",
    )
    parser.add_argument(
        "--check-config", action="store_true",
        help="validate configuration, print a summary and exit without opening the UI",
    )
    parser.add_argument(
        "--simulate", action="store_true",
        help="add a developer tray menu that fakes wake-word and face-verification events",
    )
    parser.add_argument(
        "--download-models", action="store_true",
        help="download and verify the wake-word and speech models, then exit",
    )
    parser.add_argument(
        "--list-voices", action="store_true",
        help="list installed Windows voices (for voice.tts_voice), then exit",
    )
    parser.add_argument(
        "--list-audio-devices", action="store_true",
        help="list microphones (for wake_word.input_device), then exit",
    )
    parser.add_argument("--version", action="version", version=f"Drivion {__version__}")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)

    secrets = load_secrets(args.env_file)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        # Logging isn't configured yet; stderr is the right channel here.
        print(f"Drivion configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    log_file = configure_logging(config.general.log_level, paths.log_dir(), secrets.values())
    log.info("Drivion %s starting (config file: %s)", __version__,
             args.config if args.config.exists() else "defaults")

    if args.check_config:
        print("Configuration OK")
        print(f"  config file : {args.config if args.config.exists() else '(none, using defaults)'}")
        print(f"  log file    : {log_file}")
        for provider in config.llm.providers:  # never prints the keys themselves
            state = "set" if secrets.key_for(provider) is not None else "missing/placeholder"
            print(f"  {provider:<10} key : {state}")
        print(config.model_dump_json(indent=2))
        return EXIT_OK

    if args.download_models:
        return _download_models(config)
    if args.list_audio_devices:
        return _list_audio_devices()
    if args.list_voices:
        return _list_voices()

    return _run_ui(config, secrets, simulate=args.simulate)


def _download_models(config: AppConfig) -> int:
    from drivion.audio.models import ModelDownloadError, download_models
    from drivion.speech.stt import download_whisper_model

    target = paths.models_dir()
    print(f"Downloading wake-word models to {target} ...")
    try:
        written = download_models(target)
    except ModelDownloadError as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(f"Wake word: {len(written)} downloaded, all files verified.")

    name = config.voice.stt_model
    print(f"Downloading speech model {name} (pinned revision) ...")
    try:
        download_whisper_model(target, name)
    except Exception as exc:  # network, disk and Hugging Face Hub errors
        print(f"Download failed: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(f"Speech model {name}: ready.")
    return EXIT_OK


def _list_voices() -> int:
    from drivion.speech.tts import installed_voices

    try:
        voices = installed_voices()
    except Exception as exc:
        print(f"Windows speech is unavailable: {exc}", file=sys.stderr)
        return EXIT_ERROR
    for name in voices:
        print(f"  {name}")
    print("\nSet voice.tts_voice to part of a name, e.g. \"Zira\".")
    return EXIT_OK


def _list_audio_devices() -> int:
    from drivion.audio.source import list_input_devices

    devices = list_input_devices()
    if not devices:
        print("No microphones found.")
        return EXIT_ERROR
    for index, name, host_api, is_default in devices:
        print(f"{index:>3}  [{host_api}] {name}{'   (default)' if is_default else ''}")
    print("\nSet wake_word.input_device to an index or part of a name; omit it to use the default.")
    return EXIT_OK


def _run_ui(config: AppConfig, secrets, simulate: bool) -> int:
    # Imported here so --check-config and config tests don't load Qt.
    from PySide6.QtWidgets import QApplication

    from drivion.core.single_instance import (
        SingleInstanceLock,
        instance_id,
        notify_running_instance,
    )

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Drivion")
    # The window hides in standby; that must not end the process.
    app.setQuitOnLastWindowClosed(False)

    name = instance_id()
    lock = SingleInstanceLock(name)
    if not lock.acquire():
        reached = notify_running_instance(name)
        log.info("Another Drivion is already running (asked it to open: %s)", reached)
        print("Drivion is already running" + (" - asked it to open." if reached else "."))
        return EXIT_ALREADY_RUNNING

    try:
        return _run_event_loop(app, config, secrets, simulate, name)
    finally:
        lock.release()


def _run_event_loop(app, config: AppConfig, secrets, simulate: bool, name: str) -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QSystemTrayIcon

    from drivion.core.activity import ActivityFeed
    from drivion.core.controller import AssistantController
    from drivion.core.events import Event, EventType
    from drivion.core.services import ServiceManager
    from drivion.core.single_instance import ActivationServer
    from drivion.core.state import AppState
    from drivion.ui.main_window import MainWindow
    from drivion.ui.shell import Shell
    from drivion.ui.tray import TrayIcon

    session_services = ServiceManager()
    standby_services = ServiceManager()
    active_services = ServiceManager()
    controller = AssistantController(
        config.face.verification_timeout_s,
        services=session_services,
        standby_services=standby_services,
        active_services=active_services,
    )
    feed = ActivityFeed(history_limit=config.ui.history_limit)

    wake_phrase, listening, wake_word_problem = _register_wake_word(
        config, controller, feed, standby_services
    )
    speaker = _build_speaker(config, session_services)
    processor = _build_command_processor(config, controller, feed, speaker, wake_phrase,
                                         secrets=secrets)
    voice_input, speech_problem = _register_speech(
        config, controller, feed, speaker, processor, active_services
    )

    def greet_on_activation(transition) -> None:
        if transition.new is AppState.ACTIVE and config.voice.greeting:
            speaker.say(config.voice.greeting)

    controller.state_changed.connect(greet_on_activation)

    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = TrayIcon(simulate=simulate, simulate_microphone=not (listening or voice_input))
    else:
        log.warning("No system tray available; the window will stay visible instead")
    window = MainWindow(
        history_limit=config.ui.history_limit,
        animated=config.ui.animations,
        wake_phrase=wake_phrase,
    )
    shell = Shell(controller, feed, window, tray, command_handler=processor.handle)

    activation = ActivationServer(name)
    activation.activation_requested.connect(shell.request_activation)
    activation.listen()

    controller.shutdown_finished.connect(app.quit)
    # Covers quits that don't go through "Exit Drivion" (e.g. Windows logoff).
    app.aboutToQuit.connect(lambda: controller.shutdown("application quitting"))

    # Ctrl+C in the terminal: Python only runs signal handlers between
    # bytecodes, so a no-op timer wakes the interpreter regularly.
    signal.signal(
        signal.SIGINT,
        lambda *_: controller.post_event(Event(EventType.EXIT_REQUESTED, "Ctrl+C")),
    )
    wakeup = QTimer(controller)
    wakeup.timeout.connect(lambda: None)
    wakeup.start(250)

    shell.show_initial()
    controller.start()
    if wake_word_problem:
        controller.notification.emit("Wake word unavailable", wake_word_problem)
    if speech_problem:
        controller.notification.emit("Voice commands unavailable", speech_problem)
    log.info("Drivion running (state %s, simulation %s)", controller.state,
             "on" if simulate else "off")
    # Runs once the event loop is actually processing events, i.e. when a
    # second launch's activation request can be accepted.
    QTimer.singleShot(0, lambda: log.info("Event loop started"))

    code = app.exec()
    activation.close()
    signal.signal(signal.SIGINT, signal.default_int_handler)
    log.info("Drivion exited with code %s", code)
    return code


def _register_wake_word(
    config: AppConfig, controller, feed, standby_services
) -> tuple[str, bool, str | None]:
    """Build the wake-word listener if possible.

    Returns (phrase to display, listener registered?, problem to report).
    A missing model or engine is not fatal: Drivion still runs and can be
    opened from the tray.
    """
    from drivion.audio.source import MicrophoneSource
    from drivion.audio.wake_word import (
        DEFAULT_PHRASE,
        OpenWakeWordEngine,
        WakeWordDetector,
        WakeWordService,
        WakeWordUnavailable,
        resolve_wake_word,
        sensitivity_to_threshold,
    )
    from drivion.core.activity import Device
    from drivion.core.events import Event, EventType

    settings = config.wake_word
    if not settings.enabled:
        log.info("Wake word disabled in config")
        return settings.phrase or DEFAULT_PHRASE, False, None

    try:
        model_path, phrase = resolve_wake_word(settings.model, paths.models_dir(), settings.phrase)
        engine = OpenWakeWordEngine(model_path, paths.models_dir())
    except WakeWordUnavailable as exc:
        log.warning("Wake word unavailable: %s", exc)
        return settings.phrase or DEFAULT_PHRASE, False, str(exc)

    service = WakeWordService(
        source_factory=lambda: MicrophoneSource(settings.input_device),
        engine=engine,
        detector=WakeWordDetector(sensitivity_to_threshold(settings.sensitivity), settings.cooldown_s),
        on_detected=lambda score: controller.post_event(
            Event(EventType.WAKE_WORD_DETECTED, "wake word", f"score {score:.2f}")),
        on_microphone=lambda state: feed.set_device(Device.MICROPHONE, state),
        on_crash=controller.service_crashed,
    )
    standby_services.register(service)
    log.info("Wake word ready: %r (%s)", phrase, model_path.name)
    return phrase, True, None


TIMEOUT_REPLY = "I didn't hear a command, so I'm going back to standby."


def _build_speaker(config: AppConfig, session_services):
    """Spoken replies; a silent stand-in when disabled (replies still show on screen)."""
    from drivion.speech.tts import SilentSpeaker, WindowsSpeaker

    voice = config.voice
    if voice.tts_engine == "none":
        return SilentSpeaker()
    speaker = WindowsSpeaker(voice.tts_voice, voice.tts_rate, voice.tts_volume)
    session_services.register(speaker)
    return speaker


def _windows_backends():
    from drivion.actions.handlers import Backends
    from drivion.actions.windows.audio import PycawVolume
    from drivion.actions.windows.desktop import WindowsDesktop
    from drivion.actions.windows.display import WmiBrightness
    from drivion.actions.windows.power import WindowsPower
    from drivion.actions.windows.screen import GdiScreenshotter

    return Backends(PycawVolume(), WmiBrightness(), WindowsDesktop(), GdiScreenshotter(),
                    WindowsPower())


def _build_llm(config: AppConfig, secrets, catalog, transport=None):
    """The AI fallback chain, or None when [llm] enabled = false."""
    from drivion.llm.assistant import LLMAssistant
    from drivion.llm.fallback import FallbackChat
    from drivion.llm.providers import build_providers, urllib_transport

    settings = config.llm
    if not settings.enabled:
        log.info("AI provider disabled in config")
        return None
    providers = build_providers(settings, secrets, transport or urllib_transport)
    configured = [p.name for p in providers if p.configured]
    log.info("AI fallback order: %s (keys set: %s)", " -> ".join(p.name for p in providers),
             ", ".join(configured) or "none")
    chat = FallbackChat(providers, settings.request_timeout_s, settings.max_answer_tokens,
                        settings.rate_limit_cooldown_s)
    return LLMAssistant(chat, catalog)


def _build_command_processor(config: AppConfig, controller, feed, speaker, wake_phrase: str,
                             backends=None, secrets=None, llm_transport=None):
    """Transcript -> intent -> (safety-checked action) -> reply.

    Shared by voice input and the simulation menu. ``backends`` defaults to
    the real Windows implementations and ``llm_transport`` to real HTTP;
    tests pass fakes. Without ``secrets`` no AI provider is used.
    """
    from drivion.core.activity import VoiceStatus
    from drivion.actions.handlers import PowerScheduler, build_registry
    from drivion.core.commands import CommandProcessor
    from drivion.core.events import Event, EventType
    from drivion.core.state import AppState
    from drivion.intents import schemas
    from drivion.intents.catalog import Catalog
    from drivion.intents.responder import AssistantResponder
    from drivion.safety.executor import SafeExecutor

    backends = backends or _windows_backends()
    catalog = Catalog.from_settings(config.commands)
    actions = config.actions
    power = PowerScheduler(backends.power, actions.power_delay_s,
                           hibernate=actions.sleep_method == "hibernate", notify=speaker.say)
    registry = build_registry(backends, config.commands, actions, catalog.spoken_name, power)
    executor = SafeExecutor(
        registry,
        # Actions only while unlocked (ACTIVE). Read from the listener thread;
        # reading the state attribute is atomic, and commands are only heard in
        # ACTIVE anyway - this is the second, independent check.
        is_authorized=lambda: controller.state is AppState.ACTIVE,
        confirmation_timeout_s=actions.confirmation_timeout_s,
        describe=lambda intent: schemas.describe(intent, catalog.spoken_name),
    )
    responder = AssistantResponder(
        catalog,
        # Thread-safe: the responder runs in the command listener's thread.
        on_go_to_sleep=lambda: controller.post_event(Event(EventType.SLEEP_REQUESTED, "voice")),
        wake_phrase=wake_phrase,
        executor=executor,
        cancel_scheduled=power.cancel,
        llm=_build_llm(config, secrets, catalog, llm_transport) if secrets is not None else None,
        on_thinking=lambda: feed.set_voice_status(VoiceStatus.THINKING),
    )
    return CommandProcessor(feed, speaker, responder)


def _register_speech(
    config: AppConfig, controller, feed, speaker, processor, active_services
) -> tuple[bool, str | None]:
    """Build the command listener for ACTIVE. Returns (registered?, problem to report)."""
    from drivion.audio.source import MicrophoneSource
    from drivion.core.activity import Device
    from drivion.core.events import Event, EventType
    from drivion.speech.listener import CommandListenerService
    from drivion.speech.recorder import RecorderSettings
    from drivion.speech.stt import SpeechUnavailable, WhisperTranscriber, check_whisper_model
    from drivion.speech.vad import VAD_FRAME_SAMPLES, SileroVad

    voice = config.voice
    if not voice.enabled:
        log.info("Voice commands disabled in config")
        return False, None
    try:
        model_dir = check_whisper_model(paths.models_dir(), voice.stt_model)
    except SpeechUnavailable as exc:
        log.warning("Voice commands unavailable: %s", exc)
        return False, str(exc)

    def on_timeout() -> None:
        speaker.say(TIMEOUT_REPLY)
        controller.post_event(Event(EventType.COMMAND_TIMEOUT, "command listener"))

    active_services.register(CommandListenerService(
        source_factory=lambda: MicrophoneSource(config.wake_word.input_device, VAD_FRAME_SAMPLES),
        vad_factory=SileroVad,
        # Loaded in the listener thread on first activation, then kept.
        transcriber_factory=lambda: WhisperTranscriber(model_dir, voice.stt_threads),
        speaker=speaker,
        recorder_settings=RecorderSettings(
            speech_threshold=voice.speech_threshold,
            end_silence_s=voice.end_silence_s,
            max_utterance_s=voice.max_command_s,
        ),
        command_timeout_s=voice.command_timeout_s,
        on_command=processor.handle,
        on_unclear=processor.unclear,
        on_timeout=on_timeout,
        on_microphone=lambda state: feed.set_device(Device.MICROPHONE, state),
        on_status=feed.set_voice_status,
        on_crash=controller.service_crashed,
    ))
    log.info("Voice commands ready (model %s)", voice.stt_model)
    return True, None


if __name__ == "__main__":
    sys.exit(main())
