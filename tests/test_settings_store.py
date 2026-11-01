"""Saving settings and API keys."""

import tomllib

import pytest

from drivion.config import AppConfig, ConfigError, load_config
from drivion.config.store import save_settings, to_toml, update_env


def test_toml_writer_round_trips_real_settings():
    data = {"general": {"log_level": "INFO"}, "voice": {"greeting": 'Say "hi"\n', "tts_rate": -2},
            "llm": {"providers": ["groq", "gemini"], "enabled": True, "request_timeout_s": 7.5},
            "commands": {"apps": {"chrome": {"aliases": ["browser"], "launch": "C:/x y/chrome.exe"}}}}
    assert tomllib.loads(to_toml(data)) == data


def test_defaults_can_be_written_and_read_back(tmp_path):
    path = tmp_path / "settings.toml"
    dump = AppConfig().model_dump(exclude_none=True)
    path.write_text(to_toml(dump), encoding="utf-8")
    assert load_config(path) == AppConfig()


def test_save_merges_and_keeps_other_settings(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text('[wake_word]\ncooldown_s = 3.0\n[commands.apps.spotify]\nlaunch = "s.exe"\n', encoding="utf-8")
    config = save_settings(path, {"wake_word": {"sensitivity": 0.7}})
    assert (config.wake_word.sensitivity, config.wake_word.cooldown_s) == (0.7, 3.0)
    assert load_config(path).commands.apps["spotify"].launch == "s.exe"
    assert (tmp_path / "settings.toml.bak").exists()


def test_invalid_changes_write_nothing(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text("[wake_word]\nsensitivity = 0.5\n", encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    with pytest.raises(ConfigError, match="wake_word.sensitivity"):
        save_settings(path, {"wake_word": {"sensitivity": 5}})
    assert path.read_text(encoding="utf-8") == before


def test_a_broken_file_is_not_overwritten(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text("[broken\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="wasn't changed"):
        save_settings(path, {"wake_word": {"sensitivity": 0.7}})
    assert path.read_text(encoding="utf-8") == "[broken\n"


def test_none_clears_a_setting(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text('[voice]\ntts_voice = "Zira"\n', encoding="utf-8")
    assert save_settings(path, {"voice": {"tts_voice": None}}).voice.tts_voice is None


def test_update_env_replaces_keys_and_keeps_everything_else(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comment\nDRIVION_GROQ_API_KEY=old\nOTHER=1\n", encoding="utf-8")
    update_env(env, {"DRIVION_GROQ_API_KEY": "new-key-1", "DRIVION_GEMINI_API_KEY": "new-key-2"})
    assert env.read_text(encoding="utf-8").splitlines() == [
        "# comment", "DRIVION_GROQ_API_KEY=new-key-1", "OTHER=1", "DRIVION_GEMINI_API_KEY=new-key-2"]


@pytest.mark.parametrize("bad", ["", "two words", "line\nbreak"])
def test_update_env_rejects_bad_values(tmp_path, bad):
    with pytest.raises(ConfigError):
        update_env(tmp_path / ".env", {"DRIVION_GROQ_API_KEY": bad})
