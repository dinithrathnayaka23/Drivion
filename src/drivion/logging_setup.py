"""Logging configuration: console + rotating file, with secret redaction.

The redaction filter is a safety net. Code should never log secrets in the
first place, but if a key ends up inside an exception message from a
third-party SDK, the filter replaces it before it reaches any handler.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from logging.handlers import RotatingFileHandler
from pathlib import Path

REDACTED = "[REDACTED]"

# Common API-key shapes, caught even if the value wasn't registered explicitly.
_KEY_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)(api[_-]?key|access[_-]?key|token)\s*[=:]\s*\S+"),
]

_LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"

# Third-party libraries that are chatty at INFO; their warnings still get through.
_QUIET_LIBRARIES = ("comtypes", "faster_whisper", "huggingface_hub", "httpx")


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        # Ignore very short values: redacting "a" would mangle every message.
        self._secrets = sorted({s for s in secrets if len(s) >= 6}, key=len, reverse=True)

    def redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        for pattern in _KEY_PATTERNS:
            text = pattern.sub(REDACTED, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        # Render the final message once, redact it, and drop the args so
        # handlers cannot re-insert an unredacted value.
        record.msg = self.redact(record.getMessage())
        record.args = None
        if record.exc_info:
            formatted = logging.Formatter().formatException(record.exc_info)
            record.exc_text = self.redact(formatted)
            record.exc_info = None
            record.msg = f"{record.msg}\n{record.exc_text}"
            record.exc_text = None
        return True


def configure_logging(level: str, log_dir: Path, secrets: Iterable[str] = ()) -> Path:
    """Configure the root logger and return the log file path."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "drivion.log"

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    root.setLevel(level)
    for name in _QUIET_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)

    redactor = RedactingFilter(secrets)
    formatter = logging.Formatter(_LOG_FORMAT)

    file_handler = RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    console_handler = logging.StreamHandler()
    for handler in (file_handler, console_handler):
        handler.setFormatter(formatter)
        handler.addFilter(redactor)
        root.addHandler(handler)

    return log_file
