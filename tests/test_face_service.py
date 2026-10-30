"""The face verification service and the controller's VERIFYING scope."""

import sys
import threading

import pytest

import face_fakes as ff
from drivion.core.activity import DeviceState
from drivion.core.controller import AssistantController
from drivion.core.events import Event, EventType
from drivion.core.services import ServiceManager
from drivion.core.state import AppState
from drivion.vision.service import FaceVerificationService
from drivion.vision.templates import FaceTemplates, TemplateStore
from drivion.vision.verification import Outcome, VerifySettings

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI")


@pytest.fixture
def store(tmp_path):
    return TemplateStore(tmp_path / "face")


def save_owner(store, model="fake-recognizer"):
    store.save(FaceTemplates(ff.owner_templates(), model, self_similarity_min=0.9,
                             self_similarity_median=0.95))



class Harness:
    def __init__(self, store, shots, attempt=7, **camera_kw):
        self.camera = ff.FakeCamera(shots, **camera_kw)
        self.results, self.camera_states = [], []
        self.done = threading.Event()
        self.attempt = attempt
        self.service = FaceVerificationService(
            source_factory=lambda: self.camera,
            analyzer_factory=lambda: ff.FakeAnalyzer(self.camera),
            store=store,
            settings=VerifySettings(threshold=0.55, timeout_s=5),
            current_attempt=lambda: self.attempt,
            on_result=self._result,
            on_camera=self.camera_states.append,
        )

    def _result(self, attempt, result):
        self.results.append((attempt, result))
        self.done.set()

    def run(self, wait=True):
        self.service.start()
        if wait:
            assert self.done.wait(5)
        self.service.stop()
        return self


@windows_only
def test_service_verifies_and_reports_for_its_attempt(store):
    save_owner(store)
    h = Harness(store, [ff.me()] * 5).run()
    attempt, result = h.results[0]
    assert attempt == 7 and result.outcome is Outcome.MATCH
    assert h.camera_states == [DeviceState.ACTIVE, DeviceState.OFF]
    assert h.camera.closed


def test_service_fails_closed_when_nobody_is_enrolled(store):
    h = Harness(store, [ff.me()] * 5).run()
    assert h.results[0][1].outcome is Outcome.NOT_ENROLLED
    assert not h.camera.opened  # the camera isn't even turned on
    assert h.camera_states == []


@windows_only
def test_service_reports_a_busy_camera(store):
    save_owner(store)
    h = Harness(store, [], fail_open=True).run()
    assert h.results[0][1].outcome is Outcome.CAMERA_ERROR
    assert h.camera_states == [DeviceState.ERROR]


def test_service_reports_missing_models(store):
    from drivion.vision.faces import FaceModelsUnavailable

    h = Harness(store, [])

    def no_models():
        raise FaceModelsUnavailable("missing")

    h.service._analyzer_factory = no_models
    h.run()
    assert h.results[0][1].outcome is Outcome.MODELS_MISSING


@windows_only
def test_stopping_mid_attempt_sends_nothing_and_closes_the_camera(store):
    save_owner(store)
    h = Harness(store, [], endless=True)
    h.service.start()
    threading.Event().wait(0.2)
    assert h.service.stop(timeout=3)
    assert h.results == []
    assert h.camera.closed and h.camera_states[-1] is DeviceState.OFF


def test_service_does_nothing_without_an_attempt(store):
    h = Harness(store, [ff.me()], attempt=None)
    h.service.start()
    h.service.stop(timeout=3)
    assert h.results == [] and not h.camera.opened


# ----- controller

class Recorder:
    def __init__(self):
        self.name = "face"
        self.started = self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self, timeout=2.0):
        self.stopped += 1
        return True

    @property
    def is_running(self):
        return self.started > self.stopped


def test_camera_service_runs_only_while_verifying(qtbot):
    face = Recorder()
    verifying = ServiceManager()
    verifying.register(face)
    ctrl = AssistantController(10.0, verifying_services=verifying)
    ctrl.start()
    assert not face.is_running
    ctrl.handle_event(Event(EventType.WAKE_WORD_DETECTED, "test"))
    assert face.is_running
    ctrl.handle_event(Event(EventType.VERIFICATION_SUCCEEDED, "face", attempt=ctrl.verification_attempt))
    assert ctrl.state is AppState.ACTIVE and not face.is_running  # camera off once you're in


def test_failure_notification_says_why(qtbot):
    ctrl = AssistantController(10.0)
    ctrl.start()
    ctrl.handle_event(Event(EventType.WAKE_WORD_DETECTED, "test"))
    with qtbot.waitSignal(ctrl.notification, timeout=500) as signal:
        ctrl.handle_event(Event(EventType.VERIFICATION_FAILED, "face", "face not recognised",
                                attempt=ctrl.verification_attempt))
    assert "face not recognised" in signal.args[1]
