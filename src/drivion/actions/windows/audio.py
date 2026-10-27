"""Master volume via the Windows Core Audio API (pycaw)."""

from __future__ import annotations

import threading
from typing import Protocol


class VolumeControl(Protocol):
    def get_percent(self) -> int: ...
    def set_percent(self, percent: int) -> None: ...
    def is_muted(self) -> bool: ...
    def set_muted(self, muted: bool) -> None: ...


_com_ready = threading.local()


def _ensure_com() -> None:
    # Actions run on the command-listener thread, which COM doesn't know yet.
    # Initialise once per thread and never uninitialise: releasing interfaces
    # after CoUninitialize can crash.
    if not getattr(_com_ready, "done", False):
        import comtypes

        comtypes.CoInitialize()
        _com_ready.done = True


class PycawVolume:
    def _endpoint(self):
        _ensure_com()
        from pycaw.pycaw import AudioUtilities

        return AudioUtilities.GetSpeakers().EndpointVolume

    def get_percent(self) -> int:
        return round(self._endpoint().GetMasterVolumeLevelScalar() * 100)

    def set_percent(self, percent: int) -> None:
        self._endpoint().SetMasterVolumeLevelScalar(max(0, min(100, percent)) / 100, None)

    def is_muted(self) -> bool:
        return bool(self._endpoint().GetMute())

    def set_muted(self, muted: bool) -> None:
        self._endpoint().SetMute(int(muted), None)
