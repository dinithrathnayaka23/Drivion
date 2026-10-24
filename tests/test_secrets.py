from drivion.config import load_secrets

FAKE_KEY = "test-llm-key-1234567890"


def test_no_env_file_means_no_secrets(tmp_path):
    secrets = load_secrets(tmp_path / ".env")
    assert secrets.llm_api_key is None
    assert secrets.porcupine_access_key is None
    assert secrets.values() == []


def test_secrets_loaded_from_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"DRIVION_LLM_API_KEY={FAKE_KEY}\n", encoding="utf-8")
    secrets = load_secrets(env)
    assert secrets.llm_api_key is not None
    assert secrets.llm_api_key.get_secret_value() == FAKE_KEY
    assert secrets.values() == [FAKE_KEY]


def test_blank_values_count_as_missing(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DRIVION_LLM_API_KEY=\nDRIVION_PORCUPINE_ACCESS_KEY=   \n", encoding="utf-8")
    secrets = load_secrets(env)
    assert secrets.llm_api_key is None
    assert secrets.porcupine_access_key is None


def test_real_environment_overrides_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("DRIVION_LLM_API_KEY=from-file-value\n", encoding="utf-8")
    monkeypatch.setenv("DRIVION_LLM_API_KEY", "from-environment")
    assert load_secrets(env).llm_api_key.get_secret_value() == "from-environment"


def test_secret_is_hidden_when_printed(tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"DRIVION_LLM_API_KEY={FAKE_KEY}\n", encoding="utf-8")
    secrets = load_secrets(env)
    assert FAKE_KEY not in repr(secrets)
    assert FAKE_KEY not in str(secrets)
