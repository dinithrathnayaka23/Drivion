"""Listens for spoken commands while Drivion is ACTIVE.

One background thread does it all, in order, so nothing overlaps:

    microphone frame ─► ignore while Drivion is speaking (plus a short echo tail)
                     ─► voice activity (Silero) ─► UtteranceRecorder
                     ─► finished utterance ─► Whisper ─► on_command(text)

If nobody speaks for ``command_timeout_s``, ``on_timeout`` is called once
and the controller returns Drivion to standby, which stops this service and
releases the microphone.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from drivion.audio.source import AudioDeviceError, AudioSource
from drivion.core.activity import DeviceState, VoiceStatus
from drivion.core.services import CrashHandler, ThreadedService
from drivion.speech.recorder import RecorderEvent, RecorderSettings, UtteranceRecorder
from drivion.speech.stt import Transcriber
from drivion.speech.tts import Speaker
from drivion.speech.vad import VAD_FRAME_SAMPLES, SpeechProbability

log = logging.getLogger(__name__)

# Keep ignoring the microphone briefly after Drivion stops talking: room echo
# and the speaker's own tail would otherwise be heard as a command.
ECHO_TAIL_S = 0.4


class CommandListenerService(ThreadedService):
    def __init__(
        self,
        source_factory: Callable[[], AudioSource],
        vad_factory: Callable[[], SpeechProbability],
        transcriber_factory: Callable[[], Transcriber],
        speaker: Speaker,
        recorder_settings: RecorderSettings,
        command_timeout_s: float,
        on_command: Callable[[str], None],
        on_unclear: Callable[[], None],
        on_timeout: Callable[[], None],
        on_microphone: Callable[[DeviceState], None],
        on_status: Callable[[VoiceStatus], None],
        on_crash: CrashHandler | None = None,
        clock: Callable[[], float] = time.monotonic,
        frame_samples: int = VAD_FRAME_SAMPLES,
    ) -> None:
        super().__init__("command-listener", on_crash=on_crash)
        self._source_factory = source_factory
        self._vad_factory = vad_factory
        self._transcriber_factory = transcriber_factory
        self._speaker = speaker
        self._recorder = UtteranceRecorder(recorder_settings, frame_samples)
        self._command_timeout_s = command_timeout_s
        self._on_command = on_command
        self._on_unclear = on_unclear
        self._on_timeout = on_timeout
        self._on_microphone = on_microphone
        self._on_status = on_status
        self._clock = clock
        # Models are loaded once, on first use, and reused for later sessions.
        self._vad: SpeechProbability | None = None
        self._transcriber: Transcriber | None = None
        self._source: AudioSource | None = None
        self._mic_failed = False
        self._status: VoiceStatus | None = None

    def run(self, stop_event: threading.Event) -> None:
        self._mic_failed = False
        if self._transcriber is None:
            self._set_status(VoiceStatus.LOADING)
            self._vad = self._vad_factory()
            self._transcriber = self._transcriber_factory()
        if stop_event.is_set():
            return

        self._source = self._source_factory()
        try:
            self._source.open()
        except AudioDeviceError:
            self._mic_failed = True
            raise
        self._on_microphone(DeviceState.ACTIVE)

        self._recorder.reset()
        waiting_since = self._clock()
        muted_until = 0.0
        timed_out = False

        while not stop_event.is_set():
            try:
                frame = self._source.read()
            except AudioDeviceError:
                self._mic_failed = True
                raise
            if frame is None:  # end of input (finite test sources only)
                break
            now = self._clock()

            if self._speaker.is_speaking:
                muted_until = now + ECHO_TAIL_S
            if now < muted_until:
                # Drivion is talking: discard input and restart the silence timer.
                self._set_status(VoiceStatus.SPEAKING)
                self._recorder.reset()
                waiting_since = now
                continue

            event = self._recorder.push(frame, self._vad(frame))
            if event is RecorderEvent.STARTED:
                self._set_status(VoiceStatus.HEARING)
            elif event is RecorderEvent.FINISHED:
                self._handle_utterance()
                waiting_since = self._clock()
                timed_out = False
            elif not self._recorder.is_speaking:
                self._set_status(VoiceStatus.LISTENING)
                if not timed_out and now - waiting_since >= self._command_timeout_s:
                    log.info("No command heard for %.0fs", self._command_timeout_s)
                    timed_out = True  # report once; the controller stops us
                    self._on_timeout()

    def _handle_utterance(self) -> None:
        utterance = self._recorder.utterance
        self._recorder.reset()
        self._set_status(VoiceStatus.TRANSCRIBING)
        transcript = self._transcriber.transcribe(utterance.audio)
        log.info("Heard %.1fs of speech -> %r (%.2fs to transcribe%s)",
                 utterance.duration_s, transcript.text, transcript.seconds,
                 ", cut off at the length limit" if utterance.truncated else "")
        if transcript.text:
            self._on_command(transcript.text)
        else:
            self._on_unclear()

    def _set_status(self, status: VoiceStatus) -> None:
        if status is not self._status:
            self._status = status
            self._on_status(status)

    def cleanup(self) -> None:
        # The source exists only if we got as far as opening the microphone.
        if self._source is not None:
            self._source.close()
            self._source = None
            self._on_microphone(DeviceState.ERROR if self._mic_failed else DeviceState.OFF)
        self._set_status(VoiceStatus.IDLE)
        self._status = None
