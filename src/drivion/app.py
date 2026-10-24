"""Application entry point.

Startup order matters:
1. Parse arguments.
2. Load secrets, then config (fail fast on invalid config, before any UI).
3. Configure logging with the secrets registered for redaction.
4. Either print a config report (--check-config) or start the Qt event loop.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from drivion import __version__
from drivion.config import ConfigError, load_config, load_secrets
from drivion.config import paths
from drivion.logging_setup import configure_logging

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_CONFIG_ERROR = 2


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

    return _run_ui()


def _run_ui() -> int:
    # Imported here so --check-config and tests don't need a display.
    from PySide6.QtWidgets import QApplication

    from drivion.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Drivion")
    window = MainWindow()
    window.show()
    log.info("Main window shown")
    code = app.exec()
    log.info("Drivion exited with code %s", code)
    return code


if __name__ == "__main__":
    sys.exit(main())
