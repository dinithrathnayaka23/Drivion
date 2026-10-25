import pytest

from drivion.core.activity import CommandRecord, Device, DeviceState, Outcome, VoiceStatus
from drivion.core.state import AppState
from drivion.ui.main_window import NARROW_WIDTH, MainWindow, listening_text


def make_window(qtbot, **kwargs):
    window = MainWindow(**kwargs)
    qtbot.addWidget(window)
    return window


def test_window_builds_and_shows_safe_defaults(qtbot):
    window = make_window(qtbot)
    window.show()

    assert window.windowTitle() == "Drivion"
    assert window.state_label.text() == "STANDBY"
    # Nothing touches hardware yet, so indicators must say off.
    assert window.mic_chip.text() == "● Microphone off"
    assert window.camera_chip.text() == "● Camera off"
    assert window.listening_label.text() == "Not listening (microphone off)"
    assert window.history.count == 0
    assert window.history.empty_label.isVisible()


def test_sleep_button_only_enabled_when_active(qtbot):
    window = make_window(qtbot)
    for state in AppState:
        window.set_state(state, "reason")
        assert window.sleep_button.isEnabled() == (state is AppState.ACTIVE)
        assert window.orb.state is state
    assert window.detail_label.text() == "reason"


def test_device_chips_reflect_device_state(qtbot):
    window = make_window(qtbot)
    window.set_device(Device.CAMERA, DeviceState.ACTIVE)
    assert window.camera_chip.text() == "● Camera ON"
    assert window.camera_chip.property("deviceState") == "ACTIVE"
    window.set_device(Device.MICROPHONE, DeviceState.ERROR)
    assert window.mic_chip.text() == "● Microphone unavailable"
    assert window.listening_label.text() == "Microphone unavailable"


@pytest.mark.parametrize(
    "state, mic, expected",
    [
        (AppState.STANDBY, DeviceState.ACTIVE, "Listening for “Wake up, Drivion”"),
        (AppState.ACTIVE, DeviceState.ACTIVE, "Listening for commands"),
        (AppState.ACTIVE, DeviceState.OFF, "Not listening (microphone off)"),
        (AppState.VERIFYING, DeviceState.ACTIVE, "Microphone on"),
        (AppState.ACTIVE, DeviceState.ERROR, "Microphone unavailable"),
    ],
)
def test_listening_text_is_honest(state, mic, expected):
    assert listening_text(state, mic) == expected


def test_records_show_in_conversation_and_history(qtbot):
    window = make_window(qtbot)
    window.show()
    window.add_record(CommandRecord(1, "open chrome"))
    assert window.conversation.utterance_label.text() == "“open chrome”"
    assert window.conversation.reply_label.text() == "Working on it…"

    window.update_record(CommandRecord(1, "open chrome", "Chrome opened.", Outcome.SUCCESS))
    assert window.conversation.reply_label.text() == "Chrome opened."
    assert "Chrome opened." in window.history.item_text(0)
    assert window.history.list.isVisible()


def test_history_is_newest_first_and_limited(qtbot):
    window = make_window(qtbot, history_limit=10)
    for i in range(12):
        window.add_record(CommandRecord(i, f"command {i}"))
    assert window.history.count == 10
    assert "command 11" in window.history.item_text(0)
    assert "command 2" in window.history.item_text(9)
    # Updating an item that scrolled out of the list is harmless.
    window.update_record(CommandRecord(0, "command 0", "late", Outcome.SUCCESS))


def test_update_for_older_record_does_not_replace_conversation(qtbot):
    window = make_window(qtbot)
    window.add_record(CommandRecord(1, "first"))
    window.add_record(CommandRecord(2, "second"))
    window.update_record(CommandRecord(1, "first", "done", Outcome.SUCCESS))
    assert window.conversation.utterance_label.text() == "“second”"


def test_clear_history(qtbot):
    window = make_window(qtbot)
    window.add_record(CommandRecord(1, "open chrome"))
    with qtbot.waitSignal(window.clear_history_clicked, timeout=500):
        window.history.clear_button.click()
    window.clear_history()
    assert window.history.count == 0
    assert window.conversation.utterance_label.text() == "—"
    assert not window.history.clear_button.isEnabled()


def test_layout_switches_when_narrow(qtbot):
    window = make_window(qtbot)
    window.show()
    window.resize(NARROW_WIDTH + 200, 640)
    qtbot.waitUntil(lambda: not window.is_narrow, timeout=1000)
    window.resize(NARROW_WIDTH - 200, 640)
    qtbot.waitUntil(lambda: window.is_narrow, timeout=1000)


def test_x_button_does_not_close_but_asks_shell(qtbot):
    window = make_window(qtbot)
    window.show()
    with qtbot.waitSignal(window.close_requested, timeout=500):
        assert window.close() is False
    assert window.isVisible()


def test_force_close_really_closes_and_stops_animation(qtbot):
    window = make_window(qtbot)
    window.show()
    assert window.orb.is_animating
    window.force_close()
    assert not window.isVisible()
    assert not window.orb.is_animating


def test_buttons_emit_signals(qtbot):
    window = make_window(qtbot)
    window.set_state(AppState.ACTIVE)
    with qtbot.waitSignal(window.sleep_clicked, timeout=500):
        window.sleep_button.click()
    with qtbot.waitSignal(window.exit_clicked, timeout=500):
        window.exit_button.click()


@pytest.mark.parametrize(
    "voice, expected",
    [
        (VoiceStatus.LISTENING, "Listening for commands"),
        (VoiceStatus.HEARING, "Hearing you…"),
        (VoiceStatus.TRANSCRIBING, "Working out what you said…"),
        (VoiceStatus.SPEAKING, "Speaking…"),
    ],
)
def test_voice_status_while_active(voice, expected):
    assert listening_text(AppState.ACTIVE, DeviceState.ACTIVE, voice=voice) == expected


def test_loading_message_shows_before_the_microphone_opens(qtbot):
    window = make_window(qtbot)
    window.set_state(AppState.ACTIVE)
    window.set_voice_status(VoiceStatus.LOADING)
    assert window.listening_label.text() == "Preparing speech recognition…"
    window.set_device(Device.MICROPHONE, DeviceState.ACTIVE)
    window.set_voice_status(VoiceStatus.HEARING)
    assert window.listening_label.text() == "Hearing you…"
