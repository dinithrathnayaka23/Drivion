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
        print(f"  porcupine key configured: {secrets.porcupine_access_key is not None}")
        print(f"  LLM key configured      : {secrets.llm_api_key is not None}")
        print(config.model_dump_json(indent=2))
        return EXIT_OK

    return _run_ui(config, simulate=args.simulate)


def _run_ui(config: AppConfig, simulate: bool) -> int:
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
        return _run_event_loop(app, config, simulate, name)
    finally:
        lock.release()


def _run_event_loop(app, config: AppConfig, simulate: bool, name: str) -> int:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QSystemTrayIcon

    from drivion.core.controller import AssistantController
    from drivion.core.events import Event, EventType
    from drivion.core.single_instance import ActivationServer
    from drivion.ui.main_window import MainWindow
    from drivion.ui.shell import Shell
    from drivion.ui.tray import TrayIcon

    controller = AssistantController(config.face.verification_timeout_s)

    tray = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = TrayIcon(simulate=simulate)
    else:
        log.warning("No system tray available; the window will stay visible instead")
    shell = Shell(controller, MainWindow(), tray)

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
    log.info("Drivion running (state %s, simulation %s)", controller.state,
             "on" if simulate else "off")

    code = app.exec()
    activation.close()
    signal.signal(signal.SIGINT, signal.default_int_handler)
    log.info("Drivion exited with code %s", code)
    return code


if __name__ == "__main__":
    sys.exit(main())
