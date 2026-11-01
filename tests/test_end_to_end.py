"""The whole product flow in one test: wake word -> face -> liveness -> command -> sleep.

Every real component runs on its real threads: controller, wake-word service,
face verification, liveness, command listener, parser, safety executor and
action handlers. Only the hardware and models at the edges are faked.
"""

import sys
import threading

import numpy as np
import pytest

import face_fakes as ff
from action_fakes import fake_backends
from audio_fakes import FakeSource, ScriptedEngine
from drivion import app as app_module
from drivion.audio.source import AudioDeviceError
from drivion.audio.wake_word import WakeWordDetector, WakeWordService
from drivion.config import AppConfig
from drivion.core.activity import ActivityFeed, Device, DeviceState, Outcome
from drivion.core.controller import AssistantController
from drivion.core.events import Event, EventType
from drivion.core.services import ServiceManager
from drivion.core.state import AppState
from drivion.speech.listener import CommandListenerService
from drivion.speech.recorder import RecorderSettings
from drivion.speech.stt import Transcript
from drivion.vision import service as face_service
from drivion.vision.liveness import Challenge, LivenessSettings
from drivion.vision.service import FaceVerificationService
from drivion.vision.templates import FaceTemplates, TemplateStore
from drivion.vision.verification import VerifySettings

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI face templates")

S = AppState
FRAME = 1024


class Speaker:
    is_speaking = False

    def __init__(self):
        self.said = []

    def say(self, text):
        self.said.append(text)

    def cancel(self):
        pass


class Transcriber:
    def __init__(self, texts):
        self.texts = list(texts)

    def transcribe(self, audio):
        return Transcript(self.texts.pop(0) if self.texts else "", 0.01)


def spoken(commands: int) -> list[np.ndarray]:
    loud = np.full(FRAME, 1000, dtype=np.int16)
    quiet = np.zeros(FRAME, dtype=np.int16)
    return ([loud] * 10 + [quiet] * 14) * commands


def pose(yaw=0.0):
    return ff.Shot(faces=[ff.face(yaw=yaw)], similarity=0.9)


def owner_at_camera():
    """Face match, centred, the requested left turn, back to centre."""
    return ([ff.me()] * 3 + [pose() for _ in range(4)] + [pose(0.45) for _ in range(3)]
            + [pose() for _ in range(4)])


class Rig:
    def __init__(self, tmp_path, monkeypatch, camera_shots, commands=(), wake_fails_after=None):
        monkeypatch.setattr(face_service, "pick_challenges", lambda n: [Challenge.TURN_LEFT])
        self.feed = ActivityFeed()
        self.speaker = Speaker()
        self.backends = fake_backends()
        self.standby, self.verifying, self.active = ServiceManager(), ServiceManager(), ServiceManager()
        self.controller = AssistantController(30.0, standby_services=self.standby,
                                              active_services=self.active,
                                              verifying_services=self.verifying)
        self.processor = app_module._build_command_processor(
            AppConfig(), self.controller, self.feed, self.speaker, "Hey Jarvis", backends=self.backends)
        self.wakes_left = [True]
        self.wake_fails_after = wake_fails_after

        def wake_source():
            return FakeSource([np.zeros(1280, dtype=np.int16)] * 3, endless=True,
                              fail_on_read=self.wake_fails_after)

        def wake_scores():
            return [0.0, 0.0, 0.9] if self.wakes_left and self.wakes_left.pop() else []

        self.engine = ScriptedEngine(wake_scores())
        self._wake_scores = wake_scores
        self.standby.register(WakeWordService(
            wake_source, self.engine, WakeWordDetector(0.5, 2.0),
            on_detected=lambda s: self.controller.post_event(Event(EventType.WAKE_WORD_DETECTED, "wake word")),
            on_microphone=lambda st: self.feed.set_device(Device.MICROPHONE, st),
            on_crash=self.controller.service_crashed,
        ))

        store = TemplateStore(tmp_path / "face")
        store.save(FaceTemplates(ff.owner_templates(), "fake-recognizer"))
        self.camera = ff.FakeCamera(camera_shots, endless=True)
        self.verifying.register(FaceVerificationService(
            lambda: self.camera, lambda: ff.FakeAnalyzer(self.camera), store,
            VerifySettings(threshold=0.55, timeout_s=3),
            lambda: self.controller.verification_attempt,
            lambda attempt, result: self.controller.post_event(Event(
                EventType.VERIFICATION_SUCCEEDED if result.verified else EventType.VERIFICATION_FAILED,
                "face", result.reason, attempt=attempt)),
            lambda st: self.feed.set_device(Device.CAMERA, st),
            liveness=LivenessSettings(threshold=0.55, baseline_frames=3),
            on_prompt=self.speaker.say,
        ))

        self.active.register(CommandListenerService(
            lambda: FakeSource(spoken(len(commands)), endless=True),
            lambda: (lambda frame: 0.9 if np.abs(frame).mean() > 100 else 0.0),
            lambda: Transcriber(commands),
            self.speaker, RecorderSettings(), 60.0,
            on_command=self.processor.handle, on_unclear=self.processor.unclear,
            on_timeout=lambda: None,
            on_microphone=lambda st: self.feed.set_device(Device.MICROPHONE, st),
            on_status=self.feed.set_voice_status,
            on_crash=self.controller.service_crashed,
        ))

    def stop(self):
        self.controller.shutdown("test finished")


@pytest.fixture
def rig(tmp_path, monkeypatch):
    rigs = []

    def build(*args, **kwargs):
        rigs.append(Rig(tmp_path, monkeypatch, *args, **kwargs))
        return rigs[-1]

    yield build
    for r in rigs:
        r.stop()


def test_wake_word_to_command_to_standby(qtbot, rig):
    r = rig(owner_at_camera(), commands=["Set the volume to 65%.", "Drivion, go to sleep."])
    transitions = []
    r.controller.state_changed.connect(lambda t: transitions.append(t.new))
    r.controller.start()

    qtbot.waitUntil(lambda: S.ACTIVE in transitions, timeout=10000)  # wake, face, liveness
    assert "Turn your head to your left." in r.speaker.said
    qtbot.waitUntil(lambda: r.backends.volume.percent == 65, timeout=10000)  # spoken command ran
    qtbot.waitUntil(lambda: r.controller.state is S.STANDBY, timeout=10000)  # "go to sleep"

    assert transitions == [S.VERIFYING, S.ACTIVE, S.SLEEPING, S.STANDBY]
    assert [(rec.command, rec.outcome) for rec in r.feed.history] == [
        ("Set the volume to 65%.", Outcome.SUCCESS), ("Drivion, go to sleep.", Outcome.SUCCESS)]
    assert r.feed.device_state(Device.CAMERA) is DeviceState.OFF
    # Back in standby, the wake-word listener holds the microphone again.
    qtbot.waitUntil(lambda: r.feed.device_state(Device.MICROPHONE) is DeviceState.ACTIVE, timeout=5000)


def test_a_stranger_goes_back_to_standby_and_nothing_runs(qtbot, rig):
    r = rig([ff.stranger()] * 20, commands=["Set the volume to 65%."])
    r.controller.start()
    notes = []
    r.controller.notification.connect(lambda title, text: notes.append(text))
    qtbot.waitUntil(lambda: any("face not recognised" in n for n in notes), timeout=10000)
    assert r.controller.state is S.STANDBY
    assert r.backends.volume.percent == 40 and r.feed.history == []
    qtbot.waitUntil(lambda: r.feed.device_state(Device.CAMERA) is DeviceState.OFF, timeout=3000)


def test_a_photo_passes_the_face_match_but_never_opens_the_dashboard(qtbot, rig):
    photo = [ff.me()] * 3 + [pose() for _ in range(3)] + [ff.Shot(picture=ff.frame(), faces=[], similarity=0)] * 40
    r = rig(photo)
    states = []
    r.controller.state_changed.connect(lambda t: states.append(t.new))
    notes = []
    r.controller.notification.connect(lambda title, text: notes.append(text))
    r.controller.start()
    qtbot.waitUntil(lambda: any("Access denied" in t or "failed" in t for t in notes), timeout=15000)
    assert S.ACTIVE not in states


def test_power_commands_still_need_a_yes_end_to_end(qtbot, rig):
    r = rig(owner_at_camera(), commands=["Shut down the computer.", "No."])
    r.controller.start()
    qtbot.waitUntil(lambda: len(r.feed.history) == 2 and bool(r.feed.history[1].response), timeout=15000)
    assert "Are you sure" in r.feed.history[0].response
    assert r.backends.power.calls == []


def test_microphone_failure_enters_error_and_recovers(qtbot, rig):
    r = rig([], wake_fails_after=0)
    r.engine.scores = []  # nobody says the wake word in this test
    r.controller.start()
    qtbot.waitUntil(lambda: r.controller.state is S.ERROR, timeout=5000)
    assert r.feed.device_state(Device.MICROPHONE) is DeviceState.ERROR
    r.wake_fails_after = None  # the user fixes the microphone
    r.controller.post_event(Event(EventType.RECOVER_REQUESTED, "tray"))
    qtbot.waitUntil(lambda: r.controller.state is S.STANDBY, timeout=3000)
    qtbot.waitUntil(lambda: r.feed.device_state(Device.MICROPHONE) is DeviceState.ACTIVE, timeout=3000)


def test_exit_while_active_releases_everything(qtbot, rig):
    r = rig(owner_at_camera())
    r.controller.start()
    qtbot.waitUntil(lambda: r.controller.state is S.ACTIVE, timeout=10000)
    qtbot.waitUntil(lambda: r.feed.device_state(Device.MICROPHONE) is DeviceState.ACTIVE, timeout=3000)
    r.controller.shutdown("exit")
    qtbot.waitUntil(lambda: r.feed.device_state(Device.MICROPHONE) is DeviceState.OFF, timeout=3000)
    assert threading.active_count() >= 1 and r.feed.device_state(Device.CAMERA) is DeviceState.OFF
