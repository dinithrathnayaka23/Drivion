import threading
from types import SimpleNamespace

import numpy as np

from audio_fakes import FakeSource
from drivion.core.activity import DeviceState, VoiceStatus
from drivion.speech.listener import ECHO_TAIL_S, CommandListenerService
from drivion.speech.recorder import RecorderSettings
from drivion.speech.stt import Transcript, clean_text

FRAME = 1024
FRAME_S = FRAME / 16000


def speech_frames(n):
    return [np.full(FRAME, 1000, dtype=np.int16) for _ in range(n)]


def silent_frames(n):
    return [np.zeros(FRAME, dtype=np.int16) for _ in range(n)]


def loud_vad(frame):
    """Fake VAD: loud frames are speech."""
    return 0.9 if np.abs(frame).mean() > 100 else 0.0


class FakeClock:
    """Advances one frame every time the listener reads the clock after a frame."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class TickingSource(FakeSource):
    def __init__(self, frames, clock, **kw):
        super().__init__(frames, **kw)
        self.clock = clock

    def read(self):
        self.clock.now += FRAME_S
        return super().read()


class FakeTranscriber:
    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = []

    def transcribe(self, audio):
        self.calls.append(len(audio))
        return Transcript(self.texts.pop(0) if self.texts else "", 0.01)


class FakeSpeaker:
    def __init__(self, speaking_reads=()):
        self.speaking_reads = set(speaking_reads)
        self.source = None

    @property
    def is_speaking(self):
        return self.source is not None and self.source.reads in self.speaking_reads


class Harness:
    def __init__(self, frames, texts=(), timeout_s=60.0, speaking_reads=(), **source_kw):
        self.clock = FakeClock()
        self.source = TickingSource(frames, self.clock, **source_kw)
        self.speaker = FakeSpeaker(speaking_reads)
        self.speaker.source = self.source
        self.transcriber = FakeTranscriber(texts)
        self.commands, self.unclear, self.timeouts = [], [], []
        self.mic, self.status, self.crashes = [], [], []
        self.done = threading.Event()
        self.service = CommandListenerService(
            source_factory=lambda: self.source,
            vad_factory=lambda: loud_vad,
            transcriber_factory=lambda: self.transcriber,
            speaker=self.speaker,
            recorder_settings=RecorderSettings(end_silence_s=0.5, min_speech_s=0.1),
            command_timeout_s=timeout_s,
            on_command=self.commands.append,
            on_unclear=lambda: self.unclear.append(True),
            on_timeout=lambda: self.timeouts.append(self.clock.now),
            on_microphone=self._mic,
            on_status=self.status.append,
            on_crash=lambda name, exc: self.crashes.append(str(exc)),
            clock=self.clock,
        )

    def _mic(self, state):
        self.mic.append(state)
        if state is not DeviceState.ACTIVE:
            self.done.set()

    def run(self):
        self.service.start()
        assert self.done.wait(5)
        self.service.stop()
        return self


def test_command_is_transcribed_and_reported():
    h = Harness(silent_frames(5) + speech_frames(15) + silent_frames(12), texts=["Open Chrome."]).run()
    assert h.commands == ["Open Chrome."]
    assert h.mic == [DeviceState.ACTIVE, DeviceState.OFF]
    assert h.status[:4] == [VoiceStatus.LOADING, VoiceStatus.LISTENING,
                            VoiceStatus.HEARING, VoiceStatus.TRANSCRIBING]
    assert h.status[-1] is VoiceStatus.IDLE


def test_two_commands_in_a_row():
    frames = (speech_frames(10) + silent_frames(10)) * 2
    h = Harness(frames, texts=["Open Chrome.", "Lock the computer."]).run()
    assert h.commands == ["Open Chrome.", "Lock the computer."]


def test_unclear_speech_is_reported_separately():
    h = Harness(speech_frames(10) + silent_frames(12), texts=[""]).run()
    assert h.commands == []
    assert h.unclear == [True]


def test_silence_times_out_once():
    h = Harness(silent_frames(100), timeout_s=2.0).run()  # 6.4 s of silence
    assert len(h.timeouts) == 1
    assert 2.0 <= h.timeouts[0] <= 2.2
    assert h.transcriber.calls == []


def test_speaking_resets_the_silence_timer():
    # Drivion talks during reads 20-40; the 2 s timeout restarts after it (+ echo tail).
    h = Harness(silent_frames(100), timeout_s=2.0, speaking_reads=range(20, 41)).run()
    assert len(h.timeouts) == 1
    assert h.timeouts[0] >= 41 * FRAME_S + ECHO_TAIL_S + 2.0 - 0.1
    assert VoiceStatus.SPEAKING in h.status


def test_own_voice_is_never_transcribed():
    # Loud audio while Drivion is speaking (e.g. its own voice picked up by the mic).
    h = Harness(speech_frames(20) + silent_frames(30), texts=["should not happen"],
                speaking_reads=range(0, 22)).run()
    assert h.commands == []
    assert h.transcriber.calls == []


def test_microphone_failure_reports_error():
    h = Harness([], fail_open=True).run()
    assert h.mic == [DeviceState.ERROR]
    assert h.crashes


def test_microphone_failure_mid_command_reports_error():
    h = Harness(speech_frames(20), fail_on_read=5).run()
    assert h.mic == [DeviceState.ACTIVE, DeviceState.ERROR]
    assert h.commands == []


def test_model_is_loaded_once_across_sessions():
    loads = []
    h = Harness(silent_frames(3))
    h.service._transcriber_factory = lambda: loads.append(1) or h.transcriber
    for _ in range(2):
        h.done.clear()
        h.source.frames = silent_frames(3)
        h.run()
    assert loads == [1]


# ----- transcript cleaning --------------------------------------------------------


def seg(text, no_speech=0.0):
    return SimpleNamespace(text=text, no_speech_prob=no_speech)


def test_clean_text_drops_hallucinated_segments():
    # Whisper said " you" for pure silence in a real probe (no_speech_prob 0.8).
    assert clean_text([seg(" you", 0.8)]) == ""
    assert clean_text([seg(" Open Chrome.", 0.01)]) == "Open Chrome."
    assert clean_text([seg(" Open", 0.1), seg(" thanks", 0.9), seg(" Chrome.", 0.1)]) == "Open Chrome."
    assert clean_text([seg(" ...", 0.0)]) == ""
    assert clean_text([]) == ""
