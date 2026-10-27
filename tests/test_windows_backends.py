"""The real Windows backends - read-only or harmless calls only.

Nothing here changes the volume, brightness, windows or power state.
"""

import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows APIs")


def test_volume_can_be_read():
    from drivion.actions.windows.audio import PycawVolume

    volume = PycawVolume()
    assert 0 <= volume.get_percent() <= 100
    assert isinstance(volume.is_muted(), bool)


def test_volume_can_be_read_from_a_worker_thread():
    # Actions run on the command-listener thread; COM must be initialised there.
    import threading

    from drivion.actions.windows.audio import PycawVolume

    result = []
    t = threading.Thread(target=lambda: result.append(PycawVolume().get_percent()))
    t.start()
    t.join(10)
    assert result and 0 <= result[0] <= 100


def test_brightness_is_read_or_reported_unsupported():
    from drivion.actions.windows.display import BrightnessUnsupported, WmiBrightness

    try:
        assert 0 <= WmiBrightness().get_percent() <= 100
    except BrightnessUnsupported:
        pass  # e.g. a desktop PC with an external monitor


def test_window_lookup_returns_only_that_apps_windows():
    from drivion.actions.windows.desktop import WindowsDesktop

    desktop = WindowsDesktop()
    assert desktop.app_windows("no-such-program.exe") == []
    for hwnd in desktop.app_windows("explorer.exe"):  # never the taskbar or desktop
        assert isinstance(desktop.is_minimized(hwnd), bool)


def test_screenshot_is_a_real_png(tmp_path, qapp):
    from PySide6.QtGui import QImage

    from drivion.actions.windows.screen import GdiScreenshotter

    path = tmp_path / "shot.png"
    width, height = GdiScreenshotter().capture(path)
    try:
        image = QImage(str(path))
        assert (image.width(), image.height()) == (width, height)
        assert width > 0 and height > 0
    finally:
        path.unlink()  # never leave a picture of the screen behind


@pytest.mark.parametrize("call", [
    lambda p: p.sleep(False), lambda p: p.sleep(True), lambda p: p.schedule_restart(60),
    lambda p: p.schedule_shutdown(60), lambda p: p.abort_scheduled(),
])
def test_real_power_backend_refuses_while_testing(call):
    from drivion.actions.windows.power import DRY_RUN_ENV, PowerBlocked, WindowsPower
    import os

    assert os.environ.get(DRY_RUN_ENV) == "1"  # set for every test by conftest
    with pytest.raises(PowerBlocked):
        call(WindowsPower())
