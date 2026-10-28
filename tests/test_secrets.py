import pytest

from drivion.config import load_secrets

FAKE_KEY = "test-gemini-key-1234567890"


def write_env(tmp_path, text):
    env = tmp_path / ".env"
    env.write_text(text, encoding="utf-8")
    return env


def test_no_env_file_means_no_secrets(tmp_path):
    secrets = load_secrets(tmp_path / ".env")
    for provider in ("gemini", "groq", "openrouter"):
        assert secrets.key_for(provider) is None
    assert secrets.porcupine_access_key is None
    assert secrets.values() == []


def test_provider_keys_are_loaded_from_env_file(tmp_path):
    env = write_env(tmp_path, f"DRIVION_GEMINI_API_KEY={FAKE_KEY}\nDRIVION_GROQ_API_KEY=gsk_test_9876543\n")
    secrets = load_secrets(env)
    assert secrets.key_for("gemini").get_secret_value() == FAKE_KEY
    assert secrets.key_for("groq").get_secret_value() == "gsk_test_9876543"
    assert secrets.key_for("openrouter") is None
    assert sorted(secrets.values()) == sorted([FAKE_KEY, "gsk_test_9876543"])


def test_unknown_provider_has_no_key(tmp_path):
    assert load_secrets(tmp_path / ".env").key_for("openai") is None


def test_blank_values_count_as_missing(tmp_path):
    env = write_env(tmp_path, "DRIVION_GEMINI_API_KEY=\nDRIVION_PORCUPINE_ACCESS_KEY=   \n")
    secrets = load_secrets(env)
    assert secrets.key_for("gemini") is None
    assert secrets.porcupine_access_key is None


@pytest.mark.parametrize(
    "placeholder",
    ["your-gemini-api-key-here", "YOUR_GROQ_KEY", "<paste key>", "changeme", "replace-me",
     "xxxxxxxx", "placeholder", "TODO"],
)
def test_placeholders_count_as_missing(tmp_path, placeholder):
    secrets = load_secrets(write_env(tmp_path, f"DRIVION_GEMINI_API_KEY={placeholder}\n"))
    assert secrets.key_for("gemini") is None


def test_shipped_example_file_configures_nothing(tmp_path):
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / ".env.example"
    secrets = load_secrets(example)
    assert secrets.values() == []  # placeholders only - nothing is ever sent


def test_real_environment_overrides_env_file(tmp_path, monkeypatch):
    env = write_env(tmp_path, "DRIVION_GROQ_API_KEY=from-file-value\n")
    monkeypatch.setenv("DRIVION_GROQ_API_KEY", "from-environment")
    assert load_secrets(env).key_for("groq").get_secret_value() == "from-environment"


def test_secret_is_hidden_when_printed(tmp_path):
    secrets = load_secrets(write_env(tmp_path, f"DRIVION_OPENROUTER_API_KEY={FAKE_KEY}\n"))
    assert FAKE_KEY not in repr(secrets)
    assert FAKE_KEY not in str(secrets)
