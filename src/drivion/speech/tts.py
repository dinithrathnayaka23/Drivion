"""Text-to-speech with the voices built into Windows (SAPI).

The Windows speech engine is a COM object, and COM objects must be used
from the thread that created them. So ``WindowsSpeaker`` owns one
background thread: ``say()`` only queues text, and that thread speaks it.

``is_speaking`` turns true the moment text is queued, not when audio
starts. The command listener uses it to ignore the microphone while
Drivion talks, so Drivion never transcribes its own voice.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Protocol

from drivion.core.services import ThreadedService

log = logging.getLogger(__name__)

# SAPI SpeechVoiceSpeakFlags
SVSF_ASYNC = 1
SVSF_PURGE_BEFORE_SPEAK = 2


class Speaker(Protocol):
    @property
    def is_speaking(self) -> bool: ...

    def say(self, text: str) -> None: ...

    def cancel(self) -> None:
        """Stop the current sentence and drop anything queued."""


class SilentSpeaker:
    """Used when speech output is disabled or unavailable."""

    is_speaking = False

    def say(self, text: str) -> None:
        log.info("(not spoken) %s", text)

    def cancel(self) -> None:
        pass


class WindowsSpeaker(ThreadedService):
    def __init__(self, voice: str | None = None, rate: int = 0, volume: int = 100) -> None:
        super().__init__("speech-output")
        self.voice_name = voice
        self.rate = rate
        self.volume = volume
        self.available = True
        self._queue: queue.Queue[str] = queue.Queue()
        self._busy = threading.Event()
        self._cancel = threading.Event()
        # Makes "mark busy + enqueue" and "queue empty? -> not busy" atomic, so
        # is_speaking can never read False while text is waiting to be spoken.
        self._busy_lock = threading.Lock()

    @property
    def is_speaking(self) -> bool:
        return self._busy.is_set()

    def say(self, text: str) -> None:
        if not text.strip():
            return
        if not self.available or not self.is_running:
            log.info("(not spoken: speech output unavailable) %s", text)
            return
        with self._busy_lock:
            self._busy.set()
            self._queue.put(text)

    def cancel(self) -> None:
        self._drain()
        self._cancel.set()

    def run(self, stop_event: threading.Event) -> None:
        import comtypes
        import comtypes.client

        comtypes.CoInitialize()
        try:
            try:
                voice = comtypes.client.CreateObject("SAPI.SpVoice")
                self._configure(voice)
            except Exception:
                # No speech engine or voice: keep Drivion running, just silent.
                log.exception("Windows speech output unavailable")
                self.available = False
                return
            log.info("Speech output ready (%s)", voice.Voice.GetDescription())
            while not stop_event.is_set():
                try:
                    text = self._queue.get(timeout=0.1)
                except queue.Empty:
                    self._clear_busy_if_idle()
                    continue
                self._cancel.clear()
                self._speak(voice, text, stop_event)
                self._clear_busy_if_idle()
            voice.Speak("", SVSF_ASYNC | SVSF_PURGE_BEFORE_SPEAK)
        finally:
            self._busy.clear()
            comtypes.CoUninitialize()

    def _speak(self, voice, text: str, stop_event: threading.Event) -> None:
        log.info("Speaking: %s", text)
        voice.Speak(text, SVSF_ASYNC)
        # Wait in small steps so stop/cancel can interrupt a long sentence.
        while not voice.WaitUntilDone(50):
            if stop_event.is_set() or self._cancel.is_set():
                voice.Speak("", SVSF_ASYNC | SVSF_PURGE_BEFORE_SPEAK)
                break

    def _configure(self, voice) -> None:
        voice.Rate = self.rate
        voice.Volume = self.volume
        if self.voice_name:
            voices = voice.GetVoices()
            for i in range(voices.Count):
                candidate = voices.Item(i)
                if self.voice_name.lower() in candidate.GetDescription().lower():
                    voice.Voice = candidate
                    return
            log.warning("Voice %r not found; using the Windows default", self.voice_name)

    def _clear_busy_if_idle(self) -> None:
        with self._busy_lock:
            if self._queue.empty():
                self._busy.clear()

    def _drain(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return


def installed_voices() -> list[str]:
    import comtypes
    import comtypes.client

    comtypes.CoInitialize()
    try:
        voices = comtypes.client.CreateObject("SAPI.SpVoice").GetVoices()
        return [voices.Item(i).GetDescription() for i in range(voices.Count)]
    finally:
        comtypes.CoUninitialize()
