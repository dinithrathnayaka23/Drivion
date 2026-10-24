import pytest

from drivion.core.activity import ActivityFeed, Device, DeviceState, Outcome
from drivion.core.controller import AssistantController
from drivion.core.state import AppState
from drivion.ui import shell as shell_module
from drivion.ui.main_window import MainWindow
from drivion.ui.shell import SIMULATED_COMMANDS, Shell
from drivion.ui.tray import TrayIcon

S = AppState


@pytest.fixture
def feed(qapp):
    return ActivityFeed()


@pytest.fixture
def parts(qtbot, feed, monkeypatch):
    monkeypatch.setattr(shell_module, "SIMULATED_REPLY_DELAY_MS", 10)
    controller = AssistantController(verification_timeout_s=5.0)
    window = MainWindow()
    qtbot.addWidget(window)
    tray = TrayIcon(simulate=True)
    shell = Shell(controller, feed, window, tray)
    shell.show_initial()
    controller.start()
    yield controller, window, tray, shell
    tray.hide()


def wait_state(qtbot, controller, state):
    qtbot.waitUntil(lambda: controller.state is state, timeout=1000)


def activate_via_simulator(qtbot, controller, tray):
    tray.simulate_wake_word.emit()
    wait_state(qtbot, controller, S.VERIFYING)
    tray.simulate_face_verified.emit()
    wait_state(qtbot, controller, S.ACTIVE)


def test_window_hidden_in_standby_and_shown_only_when_active(qtbot, parts):
    controller, window, tray, _ = parts
    assert not window.isVisible()
    tray.simulate_wake_word.emit()
    wait_state(qtbot, controller, S.VERIFYING)
    assert not window.isVisible()  # no dashboard before verification
    tray.simulate_face_verified.emit()
    wait_state(qtbot, controller, S.ACTIVE)
    assert window.isVisible()


def test_rejected_face_keeps_window_hidden(qtbot, parts):
    controller, window, tray, _ = parts
    tray.simulate_wake_word.emit()
    wait_state(qtbot, controller, S.VERIFYING)
    tray.simulate_face_rejected.emit()
    wait_state(qtbot, controller, S.STANDBY)
    assert not window.isVisible()


def test_go_to_sleep_hides_window_but_keeps_running(qtbot, parts):
    controller, window, tray, _ = parts
    activate_via_simulator(qtbot, controller, tray)
    window.sleep_button.click()
    wait_state(qtbot, controller, S.STANDBY)
    assert not window.isVisible()
    assert tray.isVisible() or not tray.isSystemTrayAvailable()


def test_closing_window_returns_to_standby(qtbot, parts):
    controller, window, tray, _ = parts
    activate_via_simulator(qtbot, controller, tray)
    window.close()
    wait_state(qtbot, controller, S.STANDBY)
    assert not window.isVisible()


def test_tray_exit_shuts_down_and_closes_window(qtbot, parts):
    controller, window, tray, _ = parts
    activate_via_simulator(qtbot, controller, tray)
    with qtbot.waitSignal(controller.shutdown_finished, timeout=1000):
        tray.exit_action.trigger()
    assert controller.state is S.SHUTTING_DOWN
    assert not window.isVisible()


def test_tray_menu_reflects_state(qtbot, parts):
    controller, _, tray, _ = parts
    assert tray.simulation_actions["wake"].isEnabled()
    assert not tray.sleep_action.isEnabled()
    tray.simulate_failure.emit()
    wait_state(qtbot, controller, S.ERROR)
    assert tray.recover_action.isEnabled()
    assert not tray.simulation_actions["wake"].isEnabled()
    tray.recover_action.trigger()
    wait_state(qtbot, controller, S.STANDBY)


def test_no_simulation_menu_by_default(qtbot):
    tray = TrayIcon(simulate=False)
    assert tray.simulation_actions == {}


def test_without_tray_window_stays_visible_and_x_exits(qtbot, feed):
    controller = AssistantController(verification_timeout_s=5.0)
    window = MainWindow()
    qtbot.addWidget(window)
    shell = Shell(controller, feed, window, tray=None)
    shell.show_initial()
    assert window.isVisible()
    with qtbot.waitSignal(controller.shutdown_finished, timeout=1000):
        window.close()
    assert controller.state is S.SHUTTING_DOWN


def test_second_launch_activation_starts_verification(qtbot, parts):
    controller, *_, shell = parts
    shell.request_activation()
    wait_state(qtbot, controller, S.VERIFYING)


def test_feed_drives_dashboard(qtbot, parts, feed):
    _, window, _, _ = parts
    feed.set_device(Device.MICROPHONE, DeviceState.ACTIVE)
    assert window.mic_chip.state is DeviceState.ACTIVE
    record_id = feed.add_command("open vs code")
    assert window.history.count == 1
    feed.complete_command(record_id, "VS Code opened.", Outcome.SUCCESS)
    assert window.conversation.reply_label.text() == "VS Code opened."


def test_existing_feed_state_is_shown_on_startup(qtbot, feed):
    feed.set_device(Device.CAMERA, DeviceState.ACTIVE)
    feed.add_command("earlier command")
    window = MainWindow()
    qtbot.addWidget(window)
    Shell(AssistantController(verification_timeout_s=5.0), feed, window, tray=None)
    assert window.camera_chip.state is DeviceState.ACTIVE
    assert window.history.count == 1


def test_clear_button_clears_feed_and_window(qtbot, parts, feed):
    _, window, _, _ = parts
    feed.add_command("open chrome")
    window.history.clear_button.click()
    assert feed.history == []
    assert window.history.count == 0


def test_simulated_commands_only_when_active(qtbot, parts, feed):
    controller, window, tray, shell = parts
    shell.simulate_command()
    assert feed.history == []  # ignored in STANDBY
    assert not tray.simulation_actions["command"].isEnabled()

    activate_via_simulator(qtbot, controller, tray)
    assert tray.simulation_actions["command"].isEnabled()
    tray.simulate_command.emit()
    command, reply, outcome = SIMULATED_COMMANDS[0]
    assert window.history.count == 1
    qtbot.waitUntil(lambda: feed.history[0].outcome is outcome, timeout=1000)
    assert window.conversation.reply_label.text() == reply


def test_simulated_device_toggles(qtbot, parts, feed):
    _, window, tray, _ = parts
    tray.simulate_toggle_camera.emit()
    assert feed.device_state(Device.CAMERA) is DeviceState.ACTIVE
    assert window.camera_chip.state is DeviceState.ACTIVE
    tray.simulate_toggle_camera.emit()
    assert window.camera_chip.state is DeviceState.OFF
