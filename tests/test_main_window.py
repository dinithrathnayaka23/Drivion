from drivion.core.state import AppState
from drivion.ui.main_window import MainWindow


def make_window(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    return window


def test_window_builds_and_shows_safe_defaults(qtbot):
    window = make_window(qtbot)
    window.show()

    assert window.windowTitle() == "Drivion"
    assert window.state_label.text() == "State: STANDBY"
    # Nothing touches hardware yet, so indicators must say OFF.
    assert window.mic_label.text() == "Microphone: OFF"
    assert window.camera_label.text() == "Camera: OFF"


def test_sleep_button_only_enabled_when_active(qtbot):
    window = make_window(qtbot)
    for state in AppState:
        window.set_state(state, "reason")
        assert window.sleep_button.isEnabled() == (state is AppState.ACTIVE)
    assert window.detail_label.text() == "reason"


def test_x_button_does_not_close_but_asks_shell(qtbot):
    window = make_window(qtbot)
    window.show()
    with qtbot.waitSignal(window.close_requested, timeout=500):
        assert window.close() is False
    assert window.isVisible()


def test_force_close_really_closes(qtbot):
    window = make_window(qtbot)
    window.show()
    window.force_close()
    assert not window.isVisible()


def test_buttons_emit_signals(qtbot):
    window = make_window(qtbot)
    window.set_state(AppState.ACTIVE)
    with qtbot.waitSignal(window.sleep_clicked, timeout=500):
        window.sleep_button.click()
    with qtbot.waitSignal(window.exit_clicked, timeout=500):
        window.exit_button.click()
