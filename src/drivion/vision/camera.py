"""Webcam frames, behind a tiny interface tests can fake.

The camera is opened only for enrollment and verification and closed
immediately afterwards; the dashboard's camera chip follows its real state.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)

WARM_UP_S = 0.6  # frames discarded after opening, while auto-exposure settles


class CameraError(Exception):
    """Missing camera, in use by another app, or blocked by Windows privacy settings."""


class FrameSource(Protocol):
    def open(self) -> None: ...
    def read(self) -> np.ndarray | None:
        """A BGR frame, or None at the end of a finite (test) source."""
    def close(self) -> None: ...


class OpenCVCamera:
    def __init__(self, index: int = 0, width: int = 640, height: int = 480) -> None:
        self.index, self.width, self.height = index, width, height
        self._capture = None

    def open(self) -> None:
        import cv2

        # DirectShow opens laptop webcams quickly and reliably on Windows.
        capture = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)
        if not capture.isOpened():
            capture.release()
            raise CameraError(f"Could not open camera {self.index}. Is another app using it, "
                              "or is camera access turned off in Windows privacy settings?")
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        # Webcams start under-exposed and adjust over the first few frames;
        # judging those would report "too dark" for no real reason.
        deadline = time.monotonic() + WARM_UP_S
        while time.monotonic() < deadline:
            capture.read()
        self._capture = capture
        log.info("Camera %d opened", self.index)

    def read(self) -> np.ndarray | None:
        if self._capture is None:
            raise CameraError("Camera is not open")
        ok, frame = self._capture.read()
        if not ok or frame is None:
            raise CameraError("The camera stopped sending pictures")
        return frame

    def close(self) -> None:
        capture, self._capture = self._capture, None
        if capture is not None:
            capture.release()
            log.info("Camera closed")
