from pathlib import Path

import pytest

from drivion.config import AppConfig, ConfigError, load_config

EXAMPLE_FILE = Path(__file__).resolve().parents[1] / "config" / "settings.example.toml"


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "settings.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_missing_file_uses_defaults(tmp_path):
    config = load_config(tmp_path / "does-not-exist.toml")
    assert config == AppConfig()
    assert config.face.store_raw_images is False
    assert config.llm.provider == "none"


def test_none_path_uses_defaults():
    assert load_config(None) == AppConfig()


def test_example_file_is_valid():
    config = load_config(EXAMPLE_FILE)
    assert config.wake_word.sensitivity == 0.5


def test_partial_override_keeps_other_defaults(tmp_path):
    config = load_config(write(tmp_path, "[wake_word]\nsensitivity = 0.8\n"))
    assert config.wake_word.sensitivity == 0.8
    assert config.face.similarity_threshold == AppConfig().face.similarity_threshold


@pytest.mark.parametrize(
    "toml_text, expected_fragment",
    [
        ("[wake_word]\nsensitivity = 1.5\n", "wake_word.sensitivity"),
        ("[face]\nsimilarity_threshold = -0.1\n", "face.similarity_threshold"),
        ("[face]\nliveness_mode = \"maybe\"\n", "face.liveness_mode"),
        ("[general]\nlog_level = \"LOUD\"\n", "general.log_level"),
        ("[voice]\ncommand_timeout_s = 0\n", "voice.command_timeout_s"),
        ("[ui]\nhistory_limit = 5\n", "ui.history_limit"),
        ("[ui]\nanimations = \"sometimes\"\n", "ui.animations"),
        ("[ui]\nstart_minimized = true\n", "ui.start_minimized"),  # removed in M2
        ("[wake_word]\nsensitivty = 0.5\n", "wake_word.sensitivty"),  # typo -> unknown key
        ("[unknown_section]\nx = 1\n", "unknown_section"),
    ],
)
def test_invalid_values_are_rejected(tmp_path, toml_text, expected_fragment):
    with pytest.raises(ConfigError) as info:
        load_config(write(tmp_path, toml_text))
    assert expected_fragment in str(info.value)


def test_malformed_toml_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(write(tmp_path, "[face\nthreshold = "))


def test_config_is_immutable():
    config = AppConfig()
    with pytest.raises(Exception):
        config.face.similarity_threshold = 0.0  # type: ignore[misc]


def test_wake_word_model_must_be_builtin_or_onnx(tmp_path):
    with pytest.raises(ConfigError, match="wake_word.model"):
        load_config(write(tmp_path, '[wake_word]\nmodel = "alexa"\n'))
    config = load_config(write(tmp_path, '[wake_word]\nmodel = "C:/models/wake_up_drivion.onnx"\n'))
    assert config.wake_word.model.endswith(".onnx")


@pytest.mark.parametrize("value, expected", [("1", 1), ('"Microphone Array"', "Microphone Array")])
def test_input_device_accepts_index_or_name(tmp_path, value, expected):
    config = load_config(write(tmp_path, f"[wake_word]\ninput_device = {value}\n"))
    assert config.wake_word.input_device == expected
