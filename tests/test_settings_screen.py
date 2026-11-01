"""The settings screen, and that it opens only while unlocked."""

import pytest

from drivion.config import AppConfig, load_config, load_secrets
from drivion.core.activity import ActivityFeed
from drivion.core.controller import AssistantController
from drivion.core.events import Event, EventType
from drivion.core.state import AppState
from drivion.ui.main_window import MainWindow
from drivion.ui.settings import SettingsDialog
from drivion.ui.shell import Shell


def dialog(qtbot, tmp_path, config=None, keys=(), **kw):
    d = SettingsDialog(config or AppConfig(), lambda name: name in keys, tmp_path / "settings.toml",
                       tmp_path / ".env", **kw)
    qtbot.addWidget(d)
    return d


def test_opening_and_saving_with_no_edits_changes_nothing(qtbot, tmp_path):
    d = dialog(qtbot, tmp_path)
    assert d.changes() == {}
    assert d.save() is False
    assert not (tmp_path / "settings.toml").exists()


def test_every_section_saves_and_reloads(qtbot, tmp_path):
    d = dialog(qtbot, tmp_path)
    d.tts_rate.setValue(3)
    d.tts_voice.setText("Zira")
    d.wake_sensitivity.setValue(0.65)
    d.liveness.setCurrentText("none")
    d.challenges.setValue(3)
    d.models["groq"].setText("openai/gpt-oss-20b")
    d.provider_list.item(0).setCheckState(d.provider_list.item(0).checkState().Unchecked)
    assert d.save() is True
    assert "Restart Drivion" in d.message.text()
    config = load_config(tmp_path / "settings.toml")
    assert (config.voice.tts_rate, config.voice.tts_voice) == (3, "Zira")
    assert config.wake_word.sensitivity == 0.65
    assert (config.face.liveness_mode, config.face.liveness_challenges) == ("none", 3)
    assert config.llm.groq_model == "openai/gpt-oss-20b"
    assert config.llm.providers == ["groq", "openrouter"]


def test_turning_liveness_off_shows_the_risk(qtbot, tmp_path):
    d = dialog(qtbot, tmp_path)
    d.liveness.setCurrentText("none")
    assert "photo or video" in d.liveness_warning.text()


def test_cloud_ai_switches_stay_in_sync(qtbot, tmp_path):
    d = dialog(qtbot, tmp_path)
    d.cloud_ai.setChecked(False)
    assert not d.ai_enabled.isChecked()
    assert d.changes()["llm"]["enabled"] is False


def test_keys_are_never_shown_and_go_only_to_env(qtbot, tmp_path):
    d = dialog(qtbot, tmp_path, keys=("gemini",))
    assert d.keys["gemini"].text() == ""  # never read back
    assert d.keys["gemini"].echoMode() == d.keys["gemini"].echoMode().Password
    assert "A key is set" in d.keys["gemini"].placeholderText()
    d.keys["groq"].setText("gsk-secret-value-1")
    assert d.save() is True
    assert d.keys["groq"].text() == ""
    assert "gsk-secret-value-1" in (tmp_path / ".env").read_text(encoding="utf-8")
    assert not (tmp_path / "settings.toml").exists()
    assert load_secrets(tmp_path / ".env").key_for("groq").get_secret_value() == "gsk-secret-value-1"


def test_a_bad_key_saves_nothing_at_all(qtbot, tmp_path):
    d = dialog(qtbot, tmp_path)
    d.tts_rate.setValue(3)
    d.keys["groq"].setText("two words")
    assert d.save() is False
    assert "Not saved" in d.message.text()
    assert not (tmp_path / "settings.toml").exists() and not (tmp_path / ".env").exists()


def test_recovery_buttons(qtbot, tmp_path):
    calls = []
    d = dialog(qtbot, tmp_path, on_re_enroll=lambda: calls.append("enroll"),
               on_delete_face=lambda: calls.append("delete") or True)
    d.delete_button.click()
    assert calls == ["delete"] and "deleted" in d.message.text()


# ----- only while unlocked -------------------------------------------------------------------


@pytest.fixture
def shell(qtbot, tmp_path):
    controller = AssistantController(5.0)
    window = MainWindow()
    qtbot.addWidget(window)
    made = []

    def factory():
        # Not given to qtbot: the shell deletes these windows itself when they close.
        made.append(SettingsDialog(AppConfig(), lambda name: False, tmp_path / "settings.toml",
                                   tmp_path / ".env"))
        return made[-1]

    s = Shell(controller, ActivityFeed(), window, None, settings_factory=factory)
    yield s, controller, window, made
    controller.shutdown("test teardown")


def unlock(controller):
    controller.handle_event(Event(EventType.WAKE_WORD_DETECTED, "test"))
    controller.handle_event(Event(EventType.VERIFICATION_SUCCEEDED, "test",
                                  attempt=controller.verification_attempt))


def test_settings_stay_closed_until_unlocked(qtbot, shell):
    s, controller, window, made = shell
    window.settings_button.setEnabled(True)  # even if the button were somehow clicked
    s.open_settings()
    assert made == []
    unlock(controller)
    assert controller.state is AppState.ACTIVE and window.settings_button.isEnabled()
    window.settings_button.click()
    assert len(made) == 1 and made[0].isVisible()
    s.open_settings()
    assert len(made) == 1  # raises the same window


def test_settings_close_when_drivion_locks(qtbot, shell):
    s, controller, window, made = shell
    unlock(controller)
    s.open_settings()
    controller.handle_event(Event(EventType.SLEEP_REQUESTED, "test"))
    assert not made[0].isVisible() and s.settings_dialog is None


def test_tray_settings_only_while_active(qapp):
    from drivion.ui.tray import TrayIcon

    tray = TrayIcon()
    assert not tray.settings_action.isEnabled()
    tray.set_state(AppState.ACTIVE)
    assert tray.settings_action.isEnabled()


def test_closed_settings_are_deleted_on_the_ui_thread(qtbot, shell):
    from PySide6.QtCore import QCoreApplication, QEvent
    from shiboken6 import isValid

    s, controller, _, made = shell
    unlock(controller)
    s.open_settings()
    made[0].reject()
    QCoreApplication.sendPostedEvents(made[0], QEvent.Type.DeferredDelete)
    assert s.settings_dialog is None and not isValid(made[0])
