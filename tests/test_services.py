import threading

import pytest

from drivion.core.services import ServiceManager, ThreadedService


class Ticker(ThreadedService):
    """Counts loop iterations until asked to stop."""

    def __init__(self, name="ticker", **kw):
        super().__init__(name, **kw)
        self.ticks = 0
        self.cleaned_up = threading.Event()
        self.ran_on = None

    def run(self, stop_event):
        self.ran_on = threading.current_thread()
        while not stop_event.wait(0.01):
            self.ticks += 1

    def cleanup(self):
        self.cleaned_up.set()


class Crasher(ThreadedService):
    def run(self, stop_event):
        raise RuntimeError("device lost")


class Stubborn(ThreadedService):
    """Ignores the stop flag for a while, like a blocked hardware read."""

    def __init__(self):
        super().__init__("stubborn")
        self.release = threading.Event()

    def run(self, stop_event):
        self.release.wait(5)


class Recorder:
    def __init__(self, name, log, stop_ok=True, stop_raises=False):
        self.name, self.log, self.stop_ok, self.stop_raises = name, log, stop_ok, stop_raises

    def start(self):
        self.log.append(f"start {self.name}")

    def stop(self, timeout=2.0):
        self.log.append(f"stop {self.name}")
        if self.stop_raises:
            raise RuntimeError("stop failed")
        return self.stop_ok

    is_running = False


def test_threaded_service_runs_off_main_thread_and_cleans_up():
    svc = Ticker()
    svc.start()
    assert svc.is_running
    threading.Event().wait(0.05)
    assert svc.stop() is True
    assert not svc.is_running
    assert svc.ticks > 0
    assert svc.ran_on is not threading.main_thread()
    assert svc.cleaned_up.is_set()


def test_start_twice_does_not_spawn_second_thread():
    svc = Ticker()
    svc.start()
    first = svc._thread
    svc.start()
    assert svc._thread is first
    svc.stop()


def test_service_can_restart_after_stop():
    svc = Ticker()
    svc.start()
    svc.stop()
    svc.start()
    assert svc.is_running
    svc.stop()


def test_stop_before_start_is_safe():
    assert Ticker().stop() is True


def test_crash_reports_to_handler_and_still_cleans_up():
    crashes = []
    done = threading.Event()

    def on_crash(name, exc):
        crashes.append((name, str(exc)))
        done.set()

    svc = Crasher("cam", on_crash=on_crash)
    svc.start()
    assert done.wait(2)
    assert crashes == [("cam", "device lost")]


def test_stop_reports_failure_when_service_hangs():
    svc = Stubborn()
    svc.start()
    assert svc.stop(timeout=0.05) is False
    svc.release.set()
    assert svc.stop(timeout=2) is True


def test_manager_stops_in_reverse_order_and_continues_past_failures():
    log = []
    manager = ServiceManager()
    manager.register(Recorder("a", log))
    manager.register(Recorder("b", log, stop_raises=True))
    manager.register(Recorder("c", log, stop_ok=False))
    manager.start_all()
    failed = manager.stop_all()
    assert log == ["start a", "start b", "start c", "stop c", "stop b", "stop a"]
    assert failed == ["c", "b"]


def test_manager_rolls_back_when_a_service_fails_to_start():
    log = []

    class BadStart(Recorder):
        def start(self):
            raise OSError("no camera")

    manager = ServiceManager()
    manager.register(Recorder("mic", log))
    manager.register(BadStart("camera", log))
    manager.register(Recorder("never", log))
    with pytest.raises(OSError):
        manager.start_all()
    assert log == ["start mic", "stop mic"]


def test_manager_rejects_duplicate_names():
    manager = ServiceManager()
    manager.register(Ticker("x"))
    with pytest.raises(ValueError):
        manager.register(Ticker("x"))
