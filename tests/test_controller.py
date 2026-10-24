import threading

import pytest

from drivion.core.controller import AssistantController
from drivion.core.events import Event, EventType
from drivion.core.services import ServiceManager
from drivion.core.state import AppState

S = AppState
E = EventType


class FakeService:
    def __init__(self, name="fake", fail_start=False):
        self.name = name
        self.fail_start = fail_start
        self.started = 0
        self.stopped = 0

    def start(self):
        if self.fail_start:
            raise OSError("no microphone")
        self.started += 1

    def stop(self, timeout=2.0):
        self.stopped += 1
        return True

    @property
    def is_running(self):
        return self.started > self.stopped


@pytest.fixture
def services():
    manager = ServiceManager()
    manager.register(FakeService())
    return manager


@pytest.fixture
def controller(qtbot, services):
    ctrl = AssistantController(verification_timeout_s=5.0, services=services)
    ctrl.transitions = []
    ctrl.state_changed.connect(lambda t: ctrl.transitions.append((t.old, t.new)))
    ctrl.start()
    return ctrl


def send(ctrl, kind, source="test", **kw):
    ctrl.handle_event(Event(kind, source, **kw))


def verify(ctrl):
    send(ctrl, E.VERIFICATION_SUCCEEDED, attempt=ctrl.verification_attempt)


def activate(ctrl):
    send(ctrl, E.WAKE_WORD_DETECTED)
    verify(ctrl)
    assert ctrl.state is S.ACTIVE


def test_full_happy_path(controller):
    send(controller, E.WAKE_WORD_DETECTED)
    assert controller.state is S.VERIFYING
    verify(controller)
    assert controller.state is S.ACTIVE
    send(controller, E.SLEEP_REQUESTED)
    assert controller.state is S.STANDBY
    assert controller.transitions == [
        (S.STANDBY, S.VERIFYING),
        (S.VERIFYING, S.ACTIVE),
        (S.ACTIVE, S.SLEEPING),
        (S.SLEEPING, S.STANDBY),
    ]


def test_tray_activation_also_requires_verification(controller):
    send(controller, E.ACTIVATION_REQUESTED, "tray")
    assert controller.state is S.VERIFYING


def test_duplicate_wake_word_while_verifying_is_ignored(controller):
    send(controller, E.WAKE_WORD_DETECTED)
    attempt = controller.verification_attempt
    send(controller, E.WAKE_WORD_DETECTED)
    assert controller.state is S.VERIFYING
    assert controller.verification_attempt == attempt


def test_activation_while_active_raises_window(controller, qtbot):
    activate(controller)
    with qtbot.waitSignal(controller.raise_window_requested, timeout=500):
        send(controller, E.ACTIVATION_REQUESTED, "second launch")
    assert controller.state is S.ACTIVE


def test_verification_without_attempt_id_is_rejected(controller):
    send(controller, E.WAKE_WORD_DETECTED)
    send(controller, E.VERIFICATION_SUCCEEDED)  # attempt=None
    assert controller.state is S.VERIFYING


def test_verification_failure_returns_to_standby(controller, qtbot):
    send(controller, E.WAKE_WORD_DETECTED)
    with qtbot.waitSignal(controller.notification, timeout=500):
        send(controller, E.VERIFICATION_FAILED, attempt=controller.verification_attempt)
    assert controller.state is S.STANDBY


def test_verification_timeout_fails_closed(qtbot, services):
    ctrl = AssistantController(verification_timeout_s=0.05, services=services)
    send(ctrl, E.WAKE_WORD_DETECTED)
    qtbot.waitUntil(lambda: ctrl.state is S.STANDBY, timeout=2000)


def test_late_result_from_old_attempt_cannot_unlock_new_attempt(qtbot, services):
    ctrl = AssistantController(verification_timeout_s=0.05, services=services)
    send(ctrl, E.WAKE_WORD_DETECTED)
    old_attempt = ctrl.verification_attempt
    qtbot.waitUntil(lambda: ctrl.state is S.STANDBY, timeout=2000)

    send(ctrl, E.WAKE_WORD_DETECTED)  # a new attempt starts
    send(ctrl, E.VERIFICATION_SUCCEEDED, attempt=old_attempt)  # stale answer arrives
    assert ctrl.state is S.VERIFYING


def test_verification_result_outside_verifying_is_ignored(controller):
    send(controller, E.VERIFICATION_SUCCEEDED, attempt=1)
    assert controller.state is S.STANDBY


def test_sleep_outside_active_is_ignored(controller):
    send(controller, E.SLEEP_REQUESTED)
    assert controller.state is S.STANDBY


@pytest.mark.parametrize("prepare", ["standby", "verifying", "active"])
def test_failure_enters_error_and_recover_returns_to_standby(controller, prepare):
    if prepare == "verifying":
        send(controller, E.WAKE_WORD_DETECTED)
    elif prepare == "active":
        activate(controller)
    send(controller, E.FAILURE, "mic", detail="device unplugged")
    assert controller.state is S.ERROR
    send(controller, E.FAILURE, "camera")  # second failure doesn't crash
    assert controller.state is S.ERROR
    send(controller, E.RECOVER_REQUESTED)
    assert controller.state is S.STANDBY


def test_verification_timer_stops_on_error(qtbot, services):
    ctrl = AssistantController(verification_timeout_s=0.05, services=services)
    send(ctrl, E.WAKE_WORD_DETECTED)
    send(ctrl, E.FAILURE, "camera")
    qtbot.wait(150)
    assert ctrl.state is S.ERROR  # timeout must not pull us out of ERROR


def test_exit_stops_services_once_and_ignores_later_events(controller, services, qtbot):
    activate(controller)
    with qtbot.waitSignal(controller.shutdown_finished, timeout=500):
        send(controller, E.EXIT_REQUESTED)
    assert controller.state is S.SHUTTING_DOWN

    controller.shutdown()  # second call is a no-op
    send(controller, E.WAKE_WORD_DETECTED)
    assert controller.state is S.SHUTTING_DOWN
    assert services.services[0].stopped == 1


def test_service_start_failure_enters_error(qtbot):
    manager = ServiceManager()
    manager.register(FakeService("mic", fail_start=True))
    ctrl = AssistantController(verification_timeout_s=5.0, services=manager)
    ctrl.start()
    assert ctrl.state is S.ERROR


def test_post_event_from_background_thread_is_handled_on_main_thread(controller, qtbot):
    handled_on = []
    controller.state_changed.connect(lambda _: handled_on.append(threading.current_thread()))
    worker = threading.Thread(
        target=controller.post_event, args=(Event(E.WAKE_WORD_DETECTED, "worker"),)
    )
    worker.start()
    worker.join()
    qtbot.waitUntil(lambda: controller.state is S.VERIFYING, timeout=1000)
    assert handled_on == [threading.main_thread()]


def test_service_crash_callback_moves_to_error(controller, qtbot):
    threading.Thread(
        target=controller.service_crashed, args=("wake-word", RuntimeError("boom"))
    ).start()
    qtbot.waitUntil(lambda: controller.state is S.ERROR, timeout=1000)
