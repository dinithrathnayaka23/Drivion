import threading

import pytest

from drivion.audio.models import BUILTIN_WAKE_WORDS, EMBEDDING, MELSPECTROGRAM
from drivion.audio.wake_word import (
    DEFAULT_PHRASE,
    WakeWordDetector,
    WakeWordService,
    WakeWordUnavailable,
    resolve_wake_word,
    sensitivity_to_threshold,
)
from drivion.core.activity import DeviceState
from audio_fakes import FakeSource, ScriptedEngine, silent_frames


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


@pytest.mark.parametrize(
    "sensitivity, threshold", [(0.5, 0.5), (0.8, 0.2), (0.2, 0.8), (1.0, 0.05), (0.0, 0.95)]
)
def test_sensitivity_maps_to_clamped_threshold(sensitivity, threshold):
    assert sensitivity_to_threshold(sensitivity) == pytest.approx(threshold)


def test_detector_uses_threshold():
    detector = WakeWordDetector(threshold=0.5, cooldown_s=0)
    assert not detector.update(0.49)
    assert detector.update(0.5)


def test_detector_cooldown_suppresses_repeats_from_one_utterance():
    clock = FakeClock()
    detector = WakeWordDetector(threshold=0.5, cooldown_s=2.0, clock=clock)
    assert detector.update(0.9)
    clock.now += 0.08
    assert not detector.update(0.95)  # next frame of the same utterance
    clock.now += 2.0
    assert detector.update(0.9)       # a new utterance after the cooldown


# ----- service ------------------------------------------------------------------


class Harness:
    def __init__(self, source, engine, cooldown_s=0.0):
        self.source, self.engine = source, engine
        self.detections, self.mic_states, self.crashes = [], [], []
        self.done = threading.Event()
        self.service = WakeWordService(
            source_factory=lambda: source,
            engine=engine,
            detector=WakeWordDetector(0.5, cooldown_s),
            on_detected=self.detections.append,
            on_microphone=self._mic,
            on_crash=lambda name, exc: self.crashes.append((name, str(exc))),
        )

    def _mic(self, state):
        self.mic_states.append(state)
        if state is not DeviceState.ACTIVE:
            self.done.set()

    def run_to_end(self):
        self.service.start()
        assert self.done.wait(5), "service did not finish"
        self.service.stop()


def test_detects_wake_word_and_reports_real_microphone_state():
    engine = ScriptedEngine([0.1, 0.2, 0.9, 0.1, 0.1])
    h = Harness(FakeSource(silent_frames(5)), engine)
    h.run_to_end()
    assert h.detections == [0.9]
    assert h.mic_states == [DeviceState.ACTIVE, DeviceState.OFF]
    assert h.source.opened and h.source.closed
    assert engine.resets == 2  # once on start, once after the detection


def test_cooldown_applies_inside_the_service():
    # Several high-scoring frames in a row = one spoken wake word.
    h = Harness(FakeSource(silent_frames(6)), ScriptedEngine([0.9, 0.95, 0.9, 0.2, 0.1, 0.1]),
                cooldown_s=2.0)
    h.run_to_end()
    assert len(h.detections) == 1


def test_no_detection_in_silence():
    h = Harness(FakeSource(silent_frames(20)), ScriptedEngine())
    h.run_to_end()
    assert h.detections == []
    assert h.engine.frames_seen == 20


def test_microphone_open_failure_reports_error_and_crash():
    h = Harness(FakeSource(fail_open=True), ScriptedEngine())
    h.run_to_end()
    assert h.mic_states == [DeviceState.ERROR]
    assert h.crashes and h.crashes[0][0] == "wake-word"
    assert h.detections == []


def test_microphone_failure_while_listening_reports_error():
    h = Harness(FakeSource(silent_frames(10), fail_on_read=3), ScriptedEngine())
    h.run_to_end()
    assert h.mic_states == [DeviceState.ACTIVE, DeviceState.ERROR]
    assert h.source.closed
    assert len(h.crashes) == 1


def test_stop_releases_microphone_promptly():
    source = FakeSource(endless=True)
    h = Harness(source, ScriptedEngine())
    h.service.start()
    assert h.service.is_running
    assert h.service.stop(timeout=1.0) is True
    assert source.closed
    assert h.mic_states == [DeviceState.ACTIVE, DeviceState.OFF]


def test_service_can_listen_again_after_stop():
    sources = [FakeSource(endless=True), FakeSource(endless=True)]
    h = Harness(None, ScriptedEngine())
    h.service._source_factory = lambda: sources.pop(0)
    for _ in range(2):
        h.service.start()
        assert h.service.stop(timeout=1.0)
    assert h.mic_states == [DeviceState.ACTIVE, DeviceState.OFF] * 2


# ----- resolving the configured model ----------------------------------------------


def _install(directory, *models):
    """Create placeholder model files (their content won't match the pinned hashes)."""
    for model in models:
        (directory / model.filename).write_bytes(b"x")


def test_builtin_model_without_downloads_is_unavailable(tmp_path):
    with pytest.raises(WakeWordUnavailable, match="drivion --download-models"):
        resolve_wake_word("hey_jarvis", tmp_path, None)


def test_corrupted_model_is_rejected(tmp_path):
    jarvis, _ = BUILTIN_WAKE_WORDS["hey_jarvis"]
    _install(tmp_path, MELSPECTROGRAM, EMBEDDING, jarvis)  # wrong content -> hash mismatch
    with pytest.raises(WakeWordUnavailable, match="invalid"):
        resolve_wake_word("hey_jarvis", tmp_path, None)


def test_builtin_model_phrase_and_override(tmp_path, monkeypatch):
    monkeypatch.setattr("drivion.audio.wake_word.is_valid", lambda d, m: True)
    path, phrase = resolve_wake_word("hey_jarvis", tmp_path, None)
    assert path.name == "hey_jarvis_v0.1.onnx"
    assert phrase == "Hey Jarvis"
    assert resolve_wake_word("hey_jarvis", tmp_path, "Yo Jarvis")[1] == "Yo Jarvis"


def test_custom_model_path(tmp_path, monkeypatch):
    monkeypatch.setattr("drivion.audio.wake_word.is_valid", lambda d, m: True)
    custom = tmp_path / "wake_up_drivion.onnx"
    with pytest.raises(WakeWordUnavailable, match="not found"):
        resolve_wake_word(str(custom), tmp_path, None)
    custom.write_bytes(b"model")
    path, phrase = resolve_wake_word(str(custom), tmp_path, None)
    assert path == custom
    assert phrase == DEFAULT_PHRASE
