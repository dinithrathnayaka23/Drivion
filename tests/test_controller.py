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


# ----- standby services (the wake-word listener) -----------------------------------


@pytest.fixture
def with_listener(qtbot):
    listener = FakeService("wake-word")
    standby = ServiceManager()
    standby.register(listener)
    ctrl = AssistantController(verification_timeout_s=5.0, standby_services=standby)
    ctrl.start()
    return ctrl, listener


def test_listener_runs_only_in_standby(with_listener):
    ctrl, listener = with_listener
    assert listener.is_running
    send(ctrl, E.WAKE_WORD_DETECTED)
    assert not listener.is_running  # microphone released while verifying
    verify(ctrl)
    assert not listener.is_running  # and while active
    send(ctrl, E.SLEEP_REQUESTED)
    assert listener.is_running      # listening again in standby
    assert (listener.started, listener.stopped) == (2, 1)


def test_listener_restarts_after_failed_verification_and_recovery(with_listener):
    ctrl, listener = with_listener
    send(ctrl, E.WAKE_WORD_DETECTED)
    send(ctrl, E.VERIFICATION_FAILED, attempt=ctrl.verification_attempt)
    assert listener.is_running
    send(ctrl, E.FAILURE, "mic")
    assert not listener.is_running
    send(ctrl, E.RECOVER_REQUESTED)
    assert listener.is_running


def test_listener_stopped_on_shutdown(with_listener):
    ctrl, listener = with_listener
    ctrl.shutdown()
    assert not listener.is_running


def test_listener_start_failure_enters_error(qtbot):
    standby = ServiceManager()
    standby.register(FakeService("wake-word", fail_start=True))
    ctrl = AssistantController(verification_timeout_s=5.0, standby_services=standby)
    ctrl.start()
    qtbot.waitUntil(lambda: ctrl.state is S.ERROR, timeout=1000)


# ----- active services (the command listener) and the silence timeout --------------


@pytest.fixture
def with_command_listener(qtbot):
    wake, commands = FakeService("wake-word"), FakeService("command-listener")
    standby, active = ServiceManager(), ServiceManager()
    standby.register(wake)
    active.register(commands)
    ctrl = AssistantController(5.0, standby_services=standby, active_services=active)
    ctrl.transitions = []
    ctrl.state_changed.connect(lambda t: ctrl.transitions.append((t.old, t.new)))
    ctrl.start()
    return ctrl, wake, commands


def test_command_listener_runs_only_while_active(with_command_listener):
    ctrl, wake, commands = with_command_listener
    assert wake.is_running and not commands.is_running
    activate(ctrl)
    assert commands.is_running and not wake.is_running  # never both on the mic
    send(ctrl, E.SLEEP_REQUESTED)
    assert wake.is_running and not commands.is_running


def test_command_timeout_returns_to_standby(with_command_listener, qtbot):
    ctrl, wake, commands = with_command_listener
    activate(ctrl)
    with qtbot.waitSignal(ctrl.notification, timeout=500):
        send(ctrl, E.COMMAND_TIMEOUT, "command listener")
    assert ctrl.state is S.STANDBY
    assert wake.is_running and not commands.is_running
    assert ctrl.transitions[-2:] == [(S.ACTIVE, S.SLEEPING), (S.SLEEPING, S.STANDBY)]


def test_late_command_timeout_is_ignored(with_command_listener):
    ctrl, *_ = with_command_listener
    send(ctrl, E.COMMAND_TIMEOUT)  # e.g. arrives after the user already said "go to sleep"
    assert ctrl.state is S.STANDBY


def test_exit_while_active_stops_command_listener(with_command_listener):
    ctrl, wake, commands = with_command_listener
    activate(ctrl)
    ctrl.shutdown()
    assert not commands.is_running and not wake.is_running
