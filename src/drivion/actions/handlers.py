"""Builds the action registry: one verified handler per allowed intent.

Each handler uses an injected backend (real Windows code in the app, fakes
in tests) and reports success only after checking the effect where that is
possible: volume and brightness are read back, screenshots must exist on
disk, minimize/restore must change the window state. Where Windows gives no
way to check (opening a website), the reply says what was *requested*.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from drivion.actions.registry import ActionRegistry, ActionResult, Risk
from drivion.actions.windows.audio import VolumeControl
from drivion.actions.windows.desktop import Desktop
from drivion.actions.windows.display import BrightnessControl, BrightnessUnsupported
from drivion.actions.windows.power import PowerControl
from drivion.actions.windows.screen import Screenshotter
from drivion.intents import schemas as s

log = logging.getLogger(__name__)

APP_WINDOW_WAIT_S = 5.0
SLEEP_DELAY_S = 3.0  # lets Drivion finish saying it's going to sleep


@dataclass
class Backends:
    volume: VolumeControl
    brightness: BrightnessControl
    desktop: Desktop
    screen: Screenshotter
    power: PowerControl


def wait_until(condition: Callable[[], bool], timeout_s: float, interval_s: float = 0.2,
               sleep: Callable[[float], None] = time.sleep) -> bool:
    deadline = time.monotonic() + timeout_s
    while True:
        if condition():
            return True
        if time.monotonic() >= deadline:
            return False
        sleep(interval_s)


def expand_path(raw: str) -> Path:
    import os

    return Path(os.path.expandvars(os.path.expanduser(raw)))


class PowerScheduler:
    """Runs confirmed power actions with a delay so "cancel" can still stop them."""

    def __init__(self, power: PowerControl, delay_s: int, hibernate: bool,
                 notify: Callable[[str], None], sleep_delay_s: float = SLEEP_DELAY_S,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._power = power
        self._delay_s = delay_s
        self._hibernate = hibernate
        self._notify = notify
        self._sleep_delay_s = sleep_delay_s
        self._clock = clock
        self._sleep_timer: threading.Timer | None = None
        self._scheduled: tuple[str, float] | None = None  # (what, deadline)
        self._lock = threading.Lock()

    def sleep(self) -> ActionResult:
        with self._lock:
            self._sleep_timer = threading.Timer(self._sleep_delay_s, self._do_sleep)
            self._sleep_timer.daemon = True
            self._sleep_timer.start()
        what = "hibernate" if self._hibernate else "go to sleep"
        return ActionResult(True, f"The computer will {what} in {self._sleep_delay_s:.0f} seconds.")

    def restart(self) -> ActionResult:
        return self._schedule("restart", self._power.schedule_restart)

    def shutdown(self) -> ActionResult:
        return self._schedule("shut down", self._power.schedule_shutdown)

    def cancel(self) -> str | None:
        """Cancel a scheduled power action. Returns what was said, or None if nothing was scheduled."""
        with self._lock:
            timer, self._sleep_timer = self._sleep_timer, None
            scheduled, self._scheduled = self._scheduled, None
        if timer is not None and timer.is_alive():
            timer.cancel()
            return "Okay, the computer won't go to sleep."
        if scheduled is not None and self._clock() < scheduled[1]:
            if self._power.abort_scheduled():
                return f"Okay, I've cancelled the {scheduled[0]}."
            return f"It was too late to cancel the {scheduled[0]}."
        return None

    def _schedule(self, what: str, start: Callable[[int], None]) -> ActionResult:
        start(self._delay_s)  # raises if Windows refuses -> reported as a failure
        with self._lock:
            self._scheduled = (what, self._clock() + self._delay_s)
        return ActionResult(
            True, f"The computer will {what} in {self._delay_s} seconds. Say cancel to stop it.",
            verified=True,  # shutdown.exe accepted the request
        )

    def _do_sleep(self) -> None:
        with self._lock:
            self._sleep_timer = None
        try:
            self._power.sleep(self._hibernate)
        except Exception as exc:
            log.error("Sleep failed: %s", exc)
            self._notify("Windows didn't go to sleep. On some laptops that needs "
                         "the hibernate setting; see the actions section of the settings.")


def build_registry(backends: Backends, commands, actions, names: Callable[[str], str],
                   power: PowerScheduler, wait=wait_until) -> ActionRegistry:
    """``commands``/``actions``: the [commands] and [actions] config sections."""
    b = backends
    registry = ActionRegistry()

    # ----- volume -------------------------------------------------------------------

    def set_volume(percent: int) -> ActionResult:
        b.volume.set_percent(percent)
        if percent > 0 and b.volume.is_muted():
            b.volume.set_muted(False)  # asking for a level means wanting to hear it
        actual = b.volume.get_percent()
        if abs(actual - percent) > 1:
            return ActionResult(False, f"I tried to set the volume to {percent}%, but it's at {actual}%.")
        return ActionResult(True, f"Volume set to {actual}%.", verified=True)

    def change_volume(intent: s.ChangeVolume) -> ActionResult:
        current = b.volume.get_percent()
        step = intent.amount if intent.direction == "up" else -intent.amount
        target = max(0, min(100, current + step))
        if target == current:
            return ActionResult(True, f"The volume is already at {current}%.", verified=True)
        return set_volume(target)

    def mute(muted: bool) -> ActionResult:
        b.volume.set_muted(muted)
        if b.volume.is_muted() != muted:
            return ActionResult(False, "Windows didn't change the mute setting.")
        return ActionResult(True, "Sound muted." if muted else "Sound is back on.", verified=True)

    registry.register("SET_VOLUME", "Set the master volume", Risk.LOW,
                      lambda i: set_volume(i.percent))
    registry.register("CHANGE_VOLUME", "Turn the volume up or down", Risk.LOW, change_volume)
    registry.register("MUTE", "Mute the sound", Risk.LOW, lambda i: mute(True))
    registry.register("UNMUTE", "Unmute the sound", Risk.LOW, lambda i: mute(False))

    # ----- brightness ------------------------------------------------------------------

    def brightness(compute: Callable[[int], int]) -> ActionResult:
        try:
            current = b.brightness.get_percent()
            target = max(0, min(100, compute(current)))
            if target == current:
                return ActionResult(True, f"The brightness is already at {current}%.", verified=True)
            b.brightness.set_percent(target)
            # WMI applies the change asynchronously; give it a moment.
            if not wait(lambda: abs(b.brightness.get_percent() - target) <= 1, 2.0):
                return ActionResult(False, "Windows didn't apply the new brightness.")
        except BrightnessUnsupported:
            return ActionResult(False, "I can't change the brightness of this screen.")
        return ActionResult(True, f"Brightness set to {target}%.", verified=True)

    registry.register("SET_BRIGHTNESS", "Set the screen brightness", Risk.LOW,
                      lambda i: brightness(lambda _current: i.percent))
    registry.register(
        "CHANGE_BRIGHTNESS", "Make the screen brighter or dimmer", Risk.LOW,
        lambda i: brightness(lambda c: c + (i.amount if i.direction == "up" else -i.amount)),
    )

    # ----- apps, websites and folders (allowlist only) -------------------------------

    def open_app(intent: s.OpenApp) -> ActionResult:
        entry = commands.apps.get(intent.app)
        name = names(intent.app)
        if entry is None or not entry.launch:
            return ActionResult(False, f"{name} isn't set up to be opened. Add a launch entry for it.")
        try:
            b.desktop.open_target(entry.launch)
        except OSError:
            return ActionResult(False, f"Windows couldn't find {name} on this computer.")
        if entry.process and wait(lambda: bool(b.desktop.app_windows(entry.process)),
                                  APP_WINDOW_WAIT_S):
            return ActionResult(True, f"{name} is open.", verified=True)
        return ActionResult(True, f"I've asked Windows to open {name}.")

    def open_website(intent: s.OpenWebsite) -> ActionResult:
        url = commands.websites.get(intent.site)
        if url is None:
            return ActionResult(False, "That website isn't in your list.")
        b.desktop.open_target(url)
        return ActionResult(True, f"Opening {names(intent.site)} in your browser.")

    def open_folder(intent: s.OpenFolder) -> ActionResult:
        raw = commands.folders.get(intent.folder)
        name = names(intent.folder)
        path = expand_path(raw) if raw else None
        if path is None or not path.is_dir():
            return ActionResult(False, f"Your {name} folder doesn't exist on this computer.")
        b.desktop.open_target(str(path))
        return ActionResult(True, f"Opening your {name} folder.", verified=True)

    registry.register("OPEN_APP", "Open an allowlisted app", Risk.LOW, open_app)
    registry.register("OPEN_WEBSITE", "Open an allowlisted website", Risk.LOW, open_website)
    registry.register("OPEN_FOLDER", "Open an allowlisted folder", Risk.LOW, open_folder)

    # ----- app windows ------------------------------------------------------------------

    def window_action(intent, minimize: bool) -> ActionResult:
        entry = commands.apps.get(intent.app)
        name = names(intent.app)
        if entry is None or not entry.process:
            return ActionResult(False, f"I don't know which windows belong to {name}.")
        windows = b.desktop.app_windows(entry.process)
        if not windows:
            return ActionResult(False, f"{name} isn't open.")
        for hwnd in windows:
            (b.desktop.minimize if minimize else b.desktop.restore)(hwnd)
        if not wait(lambda: all(b.desktop.is_minimized(h) == minimize for h in windows), 1.0):
            return ActionResult(False, f"Windows didn't {'minimize' if minimize else 'restore'} {name}.")
        return ActionResult(True, f"{name} {'minimized' if minimize else 'restored'}.", verified=True)

    registry.register("MINIMIZE_APP", "Minimize an allowlisted app's windows", Risk.LOW,
                      lambda i: window_action(i, True))
    registry.register("RESTORE_APP", "Restore an allowlisted app's windows", Risk.LOW,
                      lambda i: window_action(i, False))

    # ----- Windows -------------------------------------------------------------------------

    def screenshot(_intent) -> ActionResult:
        folder = expand_path(actions.screenshot_dir)
        path = folder / f"Drivion {datetime.now():%Y-%m-%d %H.%M.%S}.png"
        b.screen.capture(path)
        if not path.is_file() or path.stat().st_size == 0:
            return ActionResult(False, "The screenshot wasn't saved.")
        return ActionResult(True, f"Screenshot saved in your {folder.name} folder.", verified=True)

    def lock(_intent) -> ActionResult:
        if not b.desktop.lock():
            return ActionResult(False, "Windows didn't lock.")
        return ActionResult(True, "Locking the computer.", verified=True)

    registry.register("TAKE_SCREENSHOT", "Save a screenshot", Risk.LOW, screenshot)
    # MEDIUM: interrupts you, but loses nothing - your Windows password unlocks it.
    registry.register("LOCK_COMPUTER", "Lock Windows", Risk.MEDIUM, lock)

    # ----- power: HIGH risk, so the executor always asks first ------------------------

    registry.register("SLEEP_COMPUTER", "Put Windows to sleep", Risk.HIGH, lambda i: power.sleep())
    registry.register("RESTART_COMPUTER", "Restart Windows", Risk.HIGH, lambda i: power.restart())
    registry.register("SHUTDOWN_COMPUTER", "Shut down Windows", Risk.HIGH, lambda i: power.shutdown())
    return registry
