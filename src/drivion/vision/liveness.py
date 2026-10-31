"""Liveness: is a live person in front of the camera, not a photo?

After a face match, Drivion asks for a random sequence of head turns. A turn
is measured as the change in *signed yaw*: how far the nose moves sideways
relative to the eyes, compared with where it was when you looked straight
ahead. A real head is 3D, so the nose swings out. A flat photo is not: tilting
one foreshortens everything together, and on real detector output a 50-degree
tilt moved this value by at most 0.126, well under the 0.30 required.

What ends a check immediately:

* turning the wrong way (a replayed video guessing the sequence),
* a second face, or the face jumping position between frames (swapping pictures),
* the face being lost for too long.

After the last turn a fresh frontal match is required, so a different
person can't take over during the turns.

This raises the bar; it isn't proof of life. See docs/FACE.md for what it
can't stop (for example a live video call, or a deepfake driven in real time).
YuNet gives five landmarks and none on the eyelids, so blinks aren't checked.
"""

from __future__ import annotations

import secrets
import statistics
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from drivion.vision.camera import CameraError, FrameSource
from drivion.vision.faces import FaceAnalyzer, best_similarity
from drivion.vision.quality import Face, FrameIssue, QualityLimits, assess, signed_yaw


class Challenge(StrEnum):
    TURN_LEFT = "TURN_LEFT"
    TURN_RIGHT = "TURN_RIGHT"


PROMPTS = {Challenge.TURN_LEFT: "Turn your head to your left.",
           Challenge.TURN_RIGHT: "Turn your head to your right."}
LOOK_AHEAD = "Now look straight at the camera."


class LivenessOutcome(StrEnum):
    PASSED = "PASSED"
    TIMED_OUT = "TIMED_OUT"
    WRONG_WAY = "WRONG_WAY"
    FACE_LOST = "FACE_LOST"
    MULTIPLE_FACES = "MULTIPLE_FACES"
    FACE_CHANGED = "FACE_CHANGED"
    CAMERA_ERROR = "CAMERA_ERROR"
    CANCELLED = "CANCELLED"


REASONS = {
    LivenessOutcome.PASSED: "liveness check passed",
    LivenessOutcome.TIMED_OUT: "the head turn wasn't seen in time",
    LivenessOutcome.WRONG_WAY: "the head turned the wrong way",
    LivenessOutcome.FACE_LOST: "the face left the camera's view",
    LivenessOutcome.MULTIPLE_FACES: "more than one face appeared",
    LivenessOutcome.FACE_CHANGED: "the face changed during the check",
    LivenessOutcome.CAMERA_ERROR: "the camera stopped working",
    LivenessOutcome.CANCELLED: "the check was cancelled",
}


@dataclass(frozen=True)
class LivenessSettings:
    threshold: float               # the face-match threshold, for the final frontal check
    challenges: int = 2
    timeout_s: float = 6.0         # for each turn, including returning to centre
    turn_delta: float = 0.30       # required yaw change from your centred position
    centre_band: float = 0.15      # how close to centred counts as "looking ahead"
    hold_frames: int = 2           # frames the turn must be held, to ignore detector jitter
    baseline_frames: int = 3
    max_lost_frames: int = 15      # strong turns can briefly lose the face
    max_jump: float = 0.6          # box movement per frame, relative to face width
    mirrored: bool = False         # the camera driver mirrors the picture
    limits: QualityLimits = QualityLimits()


@dataclass(frozen=True)
class LivenessResult:
    outcome: LivenessOutcome
    completed: int = 0

    @property
    def passed(self) -> bool:
        return self.outcome is LivenessOutcome.PASSED

    @property
    def reason(self) -> str:
        return REASONS[self.outcome]


def pick_challenges(count: int, choice: Callable[[Sequence], object] = secrets.choice) -> list[Challenge]:
    """A sequence that can't be predicted (uses the OS's secure random source)."""
    return [choice(list(Challenge)) for _ in range(count)]


class _Stop(Exception):
    def __init__(self, outcome: LivenessOutcome) -> None:
        self.outcome = outcome


class _Watcher:
    """Reads frames and enforces the rules that apply on every single frame."""

    def __init__(self, source, analyzer, settings, stop_event, on_frame) -> None:
        self.source, self.analyzer, self.settings = source, analyzer, settings
        self.stop_event, self.on_frame = stop_event, on_frame
        self._previous: Face | None = None
        self._lost = 0

    def next_face(self) -> tuple[np.ndarray, Face | None]:
        """The next frame and its single face (None while briefly lost)."""
        if self.stop_event is not None and self.stop_event.is_set():
            raise _Stop(LivenessOutcome.CANCELLED)
        try:
            frame = self.source.read()
        except CameraError:
            raise _Stop(LivenessOutcome.CAMERA_ERROR) from None
        if frame is None:
            raise _Stop(LivenessOutcome.TIMED_OUT)
        faces = self.analyzer.detect(frame)
        if self.on_frame is not None:
            self.on_frame(frame, faces)
        if len(faces) > 1:
            raise _Stop(LivenessOutcome.MULTIPLE_FACES)
        if not faces:
            self._lost += 1
            if self._lost > self.settings.max_lost_frames:
                raise _Stop(LivenessOutcome.FACE_LOST)
            return frame, None
        face = faces[0]
        if self._previous is not None and self._jumped(self._previous, face):
            raise _Stop(LivenessOutcome.FACE_CHANGED)
        self._previous, self._lost = face, 0
        return frame, face

    def _jumped(self, before: Face, after: Face) -> bool:
        # Allow for movement during the frames the face was lost.
        allowed = self.settings.max_jump * before.box[2] * (1 + self._lost)
        centre_a = np.array([before.box[0] + before.box[2] / 2, before.box[1] + before.box[3] / 2])
        centre_b = np.array([after.box[0] + after.box[2] / 2, after.box[1] + after.box[3] / 2])
        return float(np.linalg.norm(centre_b - centre_a)) > allowed


def run_challenges(
    source: FrameSource,
    analyzer: FaceAnalyzer,
    templates: np.ndarray,
    settings: LivenessSettings,
    challenges: list[Challenge],
    on_prompt: Callable[[str], None],
    stop_event: threading.Event | None = None,
    on_frame: Callable[[np.ndarray, list], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> LivenessResult:
    """Run the challenges on an already-open source. Fails closed on anything unclear."""
    watcher = _Watcher(source, analyzer, settings, stop_event, on_frame)
    completed = 0
    try:
        baseline = _baseline(watcher, settings, clock)
        for challenge in challenges:
            _centre(watcher, baseline, settings, clock)
            on_prompt(PROMPTS[challenge])
            _turn(watcher, challenge, baseline, settings, clock)
            completed += 1
        on_prompt(LOOK_AHEAD)
        _final_match(watcher, baseline, templates, settings, clock)
    except _Stop as stop:
        return LivenessResult(stop.outcome, completed)
    return LivenessResult(LivenessOutcome.PASSED, completed)


def _yaw_of(face: Face, settings: LivenessSettings) -> float:
    return -signed_yaw(face) if settings.mirrored else signed_yaw(face)


def _baseline(watcher, settings, clock) -> float:
    deadline, samples = clock() + settings.timeout_s, []
    while len(samples) < settings.baseline_frames:
        if clock() >= deadline:
            raise _Stop(LivenessOutcome.TIMED_OUT)
        _, face = watcher.next_face()
        if face is not None:
            samples.append(_yaw_of(face, settings))
    return statistics.median(samples)


def _centre(watcher, baseline, settings, clock) -> None:
    deadline = clock() + settings.timeout_s
    while clock() < deadline:
        _, face = watcher.next_face()
        if face is not None and abs(_yaw_of(face, settings) - baseline) <= settings.centre_band:
            return
    raise _Stop(LivenessOutcome.TIMED_OUT)


def _turn(watcher, challenge, baseline, settings, clock) -> None:
    # Positive yaw: the nose moves to the right of the picture, which is the
    # person's left on an unmirrored camera.
    wanted = 1.0 if challenge is Challenge.TURN_LEFT else -1.0
    deadline = clock() + settings.timeout_s
    held = opposite = 0
    while clock() < deadline:
        _, face = watcher.next_face()
        if face is None:
            continue
        change = (_yaw_of(face, settings) - baseline) * wanted
        held = held + 1 if change >= settings.turn_delta else 0
        opposite = opposite + 1 if change <= -settings.turn_delta else 0
        if held >= settings.hold_frames:
            return
        if opposite >= settings.hold_frames:
            raise _Stop(LivenessOutcome.WRONG_WAY)
    raise _Stop(LivenessOutcome.TIMED_OUT)


def _final_match(watcher, baseline, templates, settings, clock) -> None:
    deadline = clock() + settings.timeout_s
    compared = False
    while clock() < deadline:
        frame, face = watcher.next_face()
        if face is None or abs(_yaw_of(face, settings) - baseline) > settings.centre_band:
            continue
        if assess(frame, [face], settings.limits) is not FrameIssue.OK:
            continue
        compared = True
        if best_similarity(watcher.analyzer.embed(frame, face), templates) >= settings.threshold:
            return
    raise _Stop(LivenessOutcome.FACE_CHANGED if compared else LivenessOutcome.TIMED_OUT)
