"""Action handlers with fake backends: what they do and how they verify it."""

import threading

import pytest

from action_fakes import FakeBrightness, FakeDesktop, FakePower, FakeScreen, FakeVolume, fake_backends
from drivion.actions.handlers import PowerScheduler, build_registry
from drivion.config.settings import ActionsSettings, CommandsSettings
from drivion.intents import schemas as s
from drivion.intents.catalog import Catalog


def check_once(condition, timeout_s, *args, **kwargs):
    return condition()  # no real waiting in tests


def make(tmp_path, power_scheduler=None, commands=None, **backend_overrides):
    backends = fake_backends(**backend_overrides)
    commands = commands or CommandsSettings()
    actions = ActionsSettings(screenshot_dir=str(tmp_path / "Screenshots"))
    power = power_scheduler or PowerScheduler(backends.power, 10, False, notify=lambda m: None)
    registry = build_registry(backends, commands, actions, Catalog.from_settings(commands).spoken_name,
                              power, wait=check_once)
    return registry, backends


def run(registry, intent):
    return registry.get(intent.kind).handler(intent)


def test_every_registered_action_is_a_known_intent_with_a_risk(tmp_path):
    registry, _ = make(tmp_path)
    kinds = {spec.kind for spec in registry.specs}
    assert kinds == {
        "SET_VOLUME", "CHANGE_VOLUME", "MUTE", "UNMUTE", "SET_BRIGHTNESS", "CHANGE_BRIGHTNESS",
        "OPEN_APP", "OPEN_WEBSITE", "OPEN_FOLDER", "MINIMIZE_APP", "RESTORE_APP",
        "TAKE_SCREENSHOT", "LOCK_COMPUTER", "SLEEP_COMPUTER", "RESTART_COMPUTER", "SHUTDOWN_COMPUTER",
    }
    high = {spec.kind for spec in registry.specs if spec.needs_confirmation}
    assert high == {"SLEEP_COMPUTER", "RESTART_COMPUTER", "SHUTDOWN_COMPUTER"}


# ----- volume ----------------------------------------------------------------------------


def test_set_volume_is_verified(tmp_path):
    registry, b = make(tmp_path)
    result = run(registry, s.SetVolume(percent=65))
    assert (result.success, result.verified, b.volume.percent) == (True, True, 65)
    assert result.message == "Volume set to 65%."


def test_volume_that_does_not_change_is_reported_as_failure(tmp_path):
    registry, _ = make(tmp_path, volume=FakeVolume(percent=40, sticky=True))
    result = run(registry, s.SetVolume(percent=80))
    assert not result.success
    assert "it's at 40%" in result.message


def test_setting_a_level_unmutes(tmp_path):
    registry, b = make(tmp_path, volume=FakeVolume(muted=True))
    run(registry, s.SetVolume(percent=30))
    assert b.volume.muted is False


@pytest.mark.parametrize(
    "start, direction, amount, expected, message",
    [(40, "up", 10, 50, "Volume set to 50%."), (95, "up", 10, 100, "Volume set to 100%."),
     (5, "down", 10, 0, "Volume set to 0%."), (100, "up", 10, 100, "already at 100%")],
)
def test_change_volume_clamps(tmp_path, start, direction, amount, expected, message):
    registry, b = make(tmp_path, volume=FakeVolume(percent=start))
    result = run(registry, s.ChangeVolume(direction=direction, amount=amount))
    assert b.volume.percent == expected
    assert message in result.message


def test_mute_and_unmute(tmp_path):
    registry, b = make(tmp_path)
    assert run(registry, s.Mute()).message == "Sound muted."
    assert b.volume.muted
    assert run(registry, s.Unmute()).verified
    assert not b.volume.muted


# ----- brightness ------------------------------------------------------------------------


def test_brightness_set_and_change(tmp_path):
    registry, b = make(tmp_path)
    assert run(registry, s.SetBrightness(percent=70)).message == "Brightness set to 70%."
    assert run(registry, s.ChangeBrightness(direction="down", amount=30)).message == "Brightness set to 40%."
    assert b.brightness.sets == [70, 40]


def test_unsupported_screen_is_reported_honestly(tmp_path):
    registry, _ = make(tmp_path, brightness=FakeBrightness(supported=False))
    result = run(registry, s.SetBrightness(percent=70))
    assert not result.success
    assert result.message == "I can't change the brightness of this screen."


# ----- opening things (allowlist) ------------------------------------------------------


def test_open_app_is_verified_by_its_window(tmp_path):
    desktop = FakeDesktop()
    desktop.starts_window["chrome.exe"] = "chrome.exe"
    registry, _ = make(tmp_path, desktop=desktop)
    result = run(registry, s.OpenApp(app="chrome"))
    assert desktop.opened == ["chrome.exe"]
    assert (result.success, result.verified, result.message) == (True, True, "google chrome is open.")


def test_open_app_without_a_window_yet_is_not_claimed_as_verified(tmp_path):
    registry, b = make(tmp_path)
    result = run(registry, s.OpenApp(app="vscode"))
    assert result.success and not result.verified
    assert result.message == "I've asked Windows to open vs code."


def test_app_that_windows_cannot_find(tmp_path):
    registry, _ = make(tmp_path, desktop=FakeDesktop(openable=set()))
    result = run(registry, s.OpenApp(app="chrome"))
    assert not result.success and "couldn't find" in result.message


def test_app_without_launch_entry_is_not_opened(tmp_path):
    commands = CommandsSettings.model_validate({"apps": {"spotify": ["music"]}})
    registry, b = make(tmp_path, commands=commands)
    result = run(registry, s.OpenApp(app="spotify"))
    assert not result.success and "isn't set up" in result.message
    assert b.desktop.opened == []


def test_open_website_uses_only_the_allowlisted_url(tmp_path):
    registry, b = make(tmp_path)
    assert run(registry, s.OpenWebsite(site="youtube")).success
    assert b.desktop.opened == ["https://www.youtube.com"]


def test_open_folder_must_exist(tmp_path):
    projects = tmp_path / "Projects"
    commands = CommandsSettings.model_validate(
        {"folders": {"projects": str(projects), "missing": str(tmp_path / "nope")}})
    registry, b = make(tmp_path, commands=commands)
    assert not run(registry, s.OpenFolder(folder="projects")).success  # not created yet
    projects.mkdir()
    result = run(registry, s.OpenFolder(folder="projects"))
    assert result.success and b.desktop.opened == [str(projects)]
    assert "doesn't exist" in run(registry, s.OpenFolder(folder="missing")).message


# ----- windows -----------------------------------------------------------------------------


def test_minimize_and_restore_are_verified(tmp_path):
    desktop = FakeDesktop(windows={"chrome.exe": {1: False, 2: False}})
    registry, _ = make(tmp_path, desktop=desktop)
    assert run(registry, s.MinimizeApp(app="chrome")).message == "google chrome minimized."
    assert desktop.windows["chrome.exe"] == {1: True, 2: True}
    assert run(registry, s.RestoreApp(app="chrome")).verified
    assert desktop.windows["chrome.exe"] == {1: False, 2: False}


def test_minimize_an_app_that_is_not_open(tmp_path):
    registry, _ = make(tmp_path)
    result = run(registry, s.MinimizeApp(app="vscode"))
    assert not result.success and result.message == "vs code isn't open."


# ----- screenshot and lock -----------------------------------------------------------------


def test_screenshot_is_saved_and_checked(tmp_path):
    registry, b = make(tmp_path)
    result = run(registry, s.TakeScreenshot())
    assert result.success and result.verified
    assert b.screen.paths[0].parent == tmp_path / "Screenshots"
    assert b.screen.paths[0].suffix == ".png"


def test_lock(tmp_path):
    registry, b = make(tmp_path)
    assert run(registry, s.LockComputer()).message == "Locking the computer."
    assert b.desktop.locked == 1
    registry, _ = make(tmp_path, desktop=FakeDesktop(lock_ok=False))
    assert not run(registry, s.LockComputer()).success


# ----- power scheduler (fakes only: never the real thing) -----------------------------


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_restart_and_shutdown_are_scheduled_with_a_delay():
    power = FakePower()
    scheduler = PowerScheduler(power, delay_s=10, hibernate=False, notify=lambda m: None)
    assert "restart in 10 seconds" in scheduler.restart().message
    assert "shut down in 10 seconds" in scheduler.shutdown().message
    assert power.calls == [("restart", 10), ("shutdown", 10)]


def test_cancel_aborts_a_scheduled_shutdown_only_within_the_delay():
    power, clock = FakePower(), Clock()
    scheduler = PowerScheduler(power, 10, False, notify=lambda m: None, clock=clock)
    scheduler.shutdown()
    clock.now = 5
    assert scheduler.cancel() == "Okay, I've cancelled the shut down."
    assert power.calls[-1] == ("abort",)
    assert scheduler.cancel() is None  # nothing left to cancel

    scheduler.restart()
    clock.now = 100  # long after the restart would have happened
    assert scheduler.cancel() is None


def test_sleep_waits_briefly_and_can_be_cancelled():
    power = FakePower()
    scheduler = PowerScheduler(power, 10, False, notify=lambda m: None, sleep_delay_s=0.2)
    scheduler.sleep()
    assert scheduler.cancel() == "Okay, the computer won't go to sleep."
    threading.Event().wait(0.4)
    assert power.calls == []


def test_sleep_runs_after_the_delay_and_reports_refusal():
    power, said, done = FakePower(refuse_sleep=True), [], threading.Event()
    scheduler = PowerScheduler(power, 10, hibernate=True, sleep_delay_s=0.05,
                               notify=lambda m: (said.append(m), done.set()))
    assert "hibernate in" in scheduler.sleep().message
    assert done.wait(2)
    assert power.calls == [("sleep", True)]
    assert "didn't go to sleep" in said[0]
