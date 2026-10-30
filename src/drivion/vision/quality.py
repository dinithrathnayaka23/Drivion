"""Is this camera frame good enough to judge a face on?

Each check maps to something the user can fix, so the UI can say *why* a
frame was rejected ("too dark", "move closer") instead of failing silently.
A frame that isn't good enough never counts for or against you: it is
skipped, which keeps poor lighting from causing a false "unknown face".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np


class FrameIssue(StrEnum):
    OK = "OK"
    NO_FACE = "NO_FACE"
    MULTIPLE_FACES = "MULTIPLE_FACES"
    TOO_DARK = "TOO_DARK"
    TOO_BRIGHT = "TOO_BRIGHT"
    BLURRY = "BLURRY"
    TOO_SMALL = "TOO_SMALL"      # face too far from the camera
    NOT_FRONTAL = "NOT_FRONTAL"  # head turned too far to compare reliably


GUIDANCE: dict[FrameIssue, str] = {
    FrameIssue.OK: "Hold still…",
    FrameIssue.NO_FACE: "No face found. Look at the camera.",
    FrameIssue.MULTIPLE_FACES: "More than one face. Only you should be in view.",
    FrameIssue.TOO_DARK: "Too dark. Turn on a light or face a window.",
    FrameIssue.TOO_BRIGHT: "Too bright. Avoid strong light behind or onto the camera.",
    FrameIssue.BLURRY: "Too blurry. Hold still and clean the camera lens.",
    FrameIssue.TOO_SMALL: "Move a little closer to the camera.",
    FrameIssue.NOT_FRONTAL: "Look straight at the camera.",
}


@dataclass(frozen=True)
class QualityLimits:
    min_brightness: float = 50.0   # mean luminance of the face, 0..255
    max_brightness: float = 220.0
    min_sharpness: float = 35.0    # variance of the Laplacian on the face
    min_face_px: int = 90          # face box width in pixels
    max_yaw: float = 0.35          # nose offset from the eye midpoint, relative to eye distance


@dataclass(frozen=True)
class Face:
    """One detected face: box (x, y, w, h), 5 landmarks, detector confidence.

    ``raw`` is the detector's own row, needed by the recognizer to align the face.
    """

    box: tuple[int, int, int, int]
    landmarks: np.ndarray  # 5x2: right eye, left eye, nose, mouth right, mouth left
    score: float
    raw: np.ndarray


def face_crop_gray(frame_bgr: np.ndarray, face: Face) -> np.ndarray:
    x, y, w, h = face.box
    height, width = frame_bgr.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    crop = frame_bgr[y0:y1, x0:x1]
    if crop.size == 0:
        return np.zeros((1, 1), dtype=np.uint8)
    # ITU-R BT.601 luma, without needing OpenCV here (keeps this module testable).
    return (crop[..., 0] * 0.114 + crop[..., 1] * 0.587 + crop[..., 2] * 0.299).astype(np.uint8)


def _sharpness(gray: np.ndarray) -> float:
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return 0.0
    g = gray.astype(np.float32)
    laplacian = (g[1:-1, :-2] + g[1:-1, 2:] + g[:-2, 1:-1] + g[2:, 1:-1] - 4 * g[1:-1, 1:-1])
    return float(laplacian.var())


def _yaw(face: Face) -> float:
    right_eye, left_eye, nose = face.landmarks[0], face.landmarks[1], face.landmarks[2]
    eye_distance = float(np.linalg.norm(left_eye - right_eye))
    if eye_distance < 1:
        return 1.0
    midpoint = (left_eye + right_eye) / 2
    return abs(float(nose[0] - midpoint[0])) / eye_distance


def assess(frame_bgr: np.ndarray, faces: list[Face], limits: QualityLimits = QualityLimits()) -> FrameIssue:
    """Check the frame. Order matters: report the most actionable problem first."""
    if not faces:
        # A face the detector can't see may simply be in the dark.
        whole = frame_bgr.mean() if frame_bgr.size else 0
        return FrameIssue.TOO_DARK if whole < limits.min_brightness * 0.6 else FrameIssue.NO_FACE
    if len(faces) > 1:
        return FrameIssue.MULTIPLE_FACES
    face = faces[0]
    if face.box[2] < limits.min_face_px:
        return FrameIssue.TOO_SMALL
    gray = face_crop_gray(frame_bgr, face)
    brightness = float(gray.mean())
    if brightness < limits.min_brightness:
        return FrameIssue.TOO_DARK
    if brightness > limits.max_brightness:
        return FrameIssue.TOO_BRIGHT
    if _yaw(face) > limits.max_yaw:
        return FrameIssue.NOT_FRONTAL
    if _sharpness(gray) < limits.min_sharpness:
        return FrameIssue.BLURRY
    return FrameIssue.OK
