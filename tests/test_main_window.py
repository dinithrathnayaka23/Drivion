from drivion.ui.main_window import MainWindow


def test_window_builds_and_shows_safe_defaults(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    assert window.windowTitle() == "Drivion"
    assert window.isVisible()
    assert window.state_label.text() == "State: STANDBY"
    # Milestone 1 never touches hardware, so indicators must say OFF.
    assert window.mic_label.text() == "Microphone: OFF"
    assert window.camera_label.text() == "Camera: OFF"


def test_window_closes_cleanly(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    assert window.close()
    assert not window.isVisible()
