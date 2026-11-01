"""Saving settings from the settings screen.

Non-secret settings go to ``config/settings.toml`` and API keys to ``.env``,
never the other way round. A change is validated with the same rules as
startup *before* anything is written, so the screen can't save a config that
would stop Drivion from starting. Writes are atomic, and the previous
settings are kept as ``settings.toml.bak``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tomllib
from collections.abc import Mapping
from pathlib import Path

from pydantic import ValidationError

from drivion.config.settings import AppConfig, ConfigError

_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _key(name: str) -> str:
    return name if _BARE_KEY.match(name) else json.dumps(name)


def _value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)  # JSON strings are valid TOML strings
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    raise TypeError(f"Can't write {type(value).__name__} to TOML")


def to_toml(data: Mapping, prefix: str = "") -> str:
    """Write nested dicts as TOML. ``None`` values are left out (TOML has no null)."""
    lines = [f"{_key(k)} = {_value(v)}" for k, v in data.items()
             if v is not None and not isinstance(v, Mapping)]
    text = "\n".join(lines) + "\n" if lines else ""
    for name, value in data.items():
        if isinstance(value, Mapping):
            table = f"{prefix}.{_key(name)}" if prefix else _key(name)
            body = to_toml(value, table)
            # A table holding only sub-tables doesn't need its own header.
            header = f"[{table}]\n" if any(not isinstance(v, Mapping) for v in value.values()) else ""
            text += ("\n" if text else "") + header + body
    return text


def _merge(base: dict, changes: Mapping) -> dict:
    merged = dict(base)
    for key, value in changes.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        elif value is None:
            merged.pop(key, None)  # back to the default
        else:
            merged[key] = value
    return merged


def save_settings(path: Path, changes: Mapping) -> AppConfig:
    """Merge ``changes`` into the settings file. Raises ``ConfigError``; nothing is written then."""
    try:
        current = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} isn't valid TOML, so it wasn't changed: {exc}") from exc
    merged = _merge(current, changes)
    try:
        config = AppConfig.model_validate(merged)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise ConfigError(problems) from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    partial = path.with_suffix(path.suffix + ".part")
    header = "# Saved by Drivion's settings screen. See settings.example.toml for every option.\n\n"
    partial.write_text(header + to_toml(merged), encoding="utf-8")
    os.replace(partial, path)
    return config


def check_env_values(values: Mapping[str, str]) -> None:
    for name, value in values.items():
        if not re.fullmatch(r"[A-Z0-9_]+", name) or not value or re.search(r"\s", value):
            raise ConfigError(f"{name}: an API key can't be empty or contain spaces")


def update_env(path: Path, values: Mapping[str, str]) -> None:
    """Set keys in the .env file, keeping every other line. The values are secrets: never log them."""
    check_env_values(values)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(values)
    for index, line in enumerate(lines):
        name = line.split("=", 1)[0].strip()
        if name in remaining:
            lines[index] = f"{name}={remaining.pop(name)}"
    lines += [f"{name}={value}" for name, value in remaining.items()]
    partial = path.with_suffix(path.suffix + ".part")
    partial.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(partial, path)
