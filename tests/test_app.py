import os
import subprocess
import sys
import time

import pytest

from drivion.app import EXIT_ALREADY_RUNNING, EXIT_CONFIG_ERROR, EXIT_OK, main
from drivion.config import paths
from drivion.core.single_instance import SingleInstanceLock, instance_id

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows named mutex")


def test_check_config_with_defaults(tmp_path, capsys):
    code = main(["--config", str(tmp_path / "none.toml"), "--env-file", str(tmp_path / ".env"),
                 "--check-config"])
    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert "Configuration OK" in out
    assert "LLM key configured      : False" in out
    assert (paths.log_dir() / "drivion.log").exists()


def test_invalid_config_exits_with_error_and_no_ui(tmp_path, capsys):
    bad = tmp_path / "settings.toml"
    bad.write_text("[face]\nsimilarity_threshold = 7\n", encoding="utf-8")
    code = main(["--config", str(bad), "--check-config"])
    assert code == EXIT_CONFIG_ERROR
    assert "face.similarity_threshold" in capsys.readouterr().err


def test_check_config_does_not_print_secret(tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_text("DRIVION_LLM_API_KEY=very-private-key-123\n", encoding="utf-8")
    main(["--config", str(tmp_path / "none.toml"), "--env-file", str(env), "--check-config"])
    out = capsys.readouterr().out
    assert "very-private-key-123" not in out
    assert "LLM key configured      : True" in out


def test_data_dir_respects_override(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIVION_DATA_DIR", str(tmp_path / "x"))
    assert paths.data_dir() == tmp_path / "x"


@windows_only
def test_second_launch_exits_when_already_running(qapp, tmp_path, capsys):
    with SingleInstanceLock(instance_id()) as held:
        assert held.acquired
        code = main(["--config", str(tmp_path / "none.toml"), "--env-file", str(tmp_path / ".env")])
    assert code == EXIT_ALREADY_RUNNING
    assert "already running" in capsys.readouterr().out


def _wait_for_log(log_file, text, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if log_file.exists() and text in log_file.read_text(encoding="utf-8", errors="replace"):
            return True
        time.sleep(0.1)
    return False


@windows_only
def test_two_real_processes_only_one_runs(tmp_path):
    """Integration: launch Drivion twice as separate processes."""
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    cmd = [sys.executable, "-m", "drivion",
           "--config", str(tmp_path / "none.toml"), "--env-file", str(tmp_path / ".env")]
    log_file = paths.log_dir() / "drivion.log"

    # DEVNULL, not PIPE: nobody reads the first instance's console output, and
    # a full pipe would block its next log write (we read the log file instead).
    first = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # Wait until its event loop runs, i.e. it can accept activation requests.
        assert _wait_for_log(log_file, "Event loop started"), "first instance never started"

        second = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
        details = f"stdout={second.stdout!r} stderr={second.stderr[-500:]!r}"
        assert second.returncode == EXIT_ALREADY_RUNNING, details
        assert "asked it to open" in second.stdout, details

        assert _wait_for_log(log_file, "Activation requested by another Drivion launch")
        assert first.poll() is None  # the first instance is unaffected
    finally:
        first.kill()
        first.wait(10)


# ----- wake word wiring and CLI ----------------------------------------------------

from drivion import app as app_module  # noqa: E402
from drivion.config import AppConfig  # noqa: E402
from drivion.core.activity import ActivityFeed  # noqa: E402
from drivion.core.controller import AssistantController  # noqa: E402
from drivion.core.services import ServiceManager  # noqa: E402


def _register(qapp, config):
    standby = ServiceManager()
    controller = AssistantController(5.0, standby_services=standby)
    result = app_module._register_wake_word(config, controller, ActivityFeed(), standby)
    return result, standby


def test_missing_models_disable_listener_but_not_the_app(qapp):
    (phrase, listening, problem), standby = _register(qapp, AppConfig())
    assert listening is False
    assert "drivion --download-models" in problem
    assert standby.services == []
    assert phrase == "Wake up, Drivion"


def test_disabled_wake_word_is_quiet(qapp):
    config = AppConfig.model_validate({"wake_word": {"enabled": False}})
    (_, listening, problem), standby = _register(qapp, config)
    assert (listening, problem) == (False, None)
    assert standby.services == []


def test_list_audio_devices(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("drivion.audio.source.list_input_devices",
                        lambda: [(1, "Microphone Array", "MME", True),
                                 (4, "USB Headset", "Windows WASAPI", False)])
    code = main(["--config", str(tmp_path / "none.toml"), "--list-audio-devices"])
    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert "[MME] Microphone Array   (default)" in out
    assert "[Windows WASAPI] USB Headset" in out


def test_download_failure_exits_with_error(monkeypatch, capsys, tmp_path):
    from drivion.audio.models import ModelDownloadError

    def fail(_target):
        raise ModelDownloadError("offline")

    monkeypatch.setattr("drivion.audio.models.download_models", fail)
    code = main(["--config", str(tmp_path / "none.toml"), "--download-models"])
    assert code == app_module.EXIT_ERROR
    assert "offline" in capsys.readouterr().err


def _register_speech(qapp, config):
    from drivion.speech.tts import SilentSpeaker

    active = ServiceManager()
    controller = AssistantController(5.0, active_services=active)
    result = app_module._register_speech(config, controller, ActivityFeed(), SilentSpeaker(), active)
    return result, active


def test_missing_speech_model_disables_voice_commands_only(qapp):
    (registered, problem), active = _register_speech(qapp, AppConfig())
    assert registered is False
    assert "drivion --download-models" in problem
    assert active.services == []


def test_disabled_voice_commands_are_quiet(qapp):
    config = AppConfig.model_validate({"voice": {"enabled": False}})
    (registered, problem), active = _register_speech(qapp, config)
    assert (registered, problem) == (False, None)


def test_speech_output_can_be_turned_off():
    from drivion.speech.tts import SilentSpeaker

    services = ServiceManager()
    config = AppConfig.model_validate({"voice": {"tts_engine": "none"}})
    assert isinstance(app_module._build_speaker(config, services), SilentSpeaker)
    assert services.services == []
