"""Deciding "is this the enrolled person?" from a stream of camera frames.

Rules (fail closed - anything unclear is a "no"):

* Only frames that pass the quality checks count. A dark, blurry, too-far or
  two-person frame is neither a match nor a mismatch; it is skipped.
* A good frame *matches* if its best cosine similarity to your templates is
  at least the threshold; otherwise it is an *unknown face*.
* Success needs ``required_matches`` matching frames before the deadline,
  and more matches than unknown-face frames.
* ``max_unknown`` unknown-face frames end the attempt early: a stranger
  doesn't get to keep trying until the timeout.
* At the deadline, the result names the main problem (no face, two faces,
  poor lighting...) so the user knows what to fix.

Face matching alone can't tell a live face from a good photo or video of
it; that needs a liveness check (Milestone 10).
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np

from drivion.vision.camera import CameraError, FrameSource
from drivion.vision.faces import FaceAnalyzer, best_similarity, similarity
from drivion.vision.quality import FrameIssue, QualityLimits, assess


class Outcome(StrEnum):
    MATCH = "MATCH"
    UNKNOWN_FACE = "UNKNOWN_FACE"
    NO_FACE = "NO_FACE"
    MULTIPLE_FACES = "MULTIPLE_FACES"
    POOR_LIGHT = "POOR_LIGHT"
    POOR_QUALITY = "POOR_QUALITY"
    CAMERA_ERROR = "CAMERA_ERROR"
    NOT_ENROLLED = "NOT_ENROLLED"
    MODELS_MISSING = "MODELS_MISSING"
    CANCELLED = "CANCELLED"


REASONS: dict[Outcome, str] = {
    Outcome.MATCH: "face verified",
    Outcome.UNKNOWN_FACE: "face not recognised",
    Outcome.NO_FACE: "no face in view",
    Outcome.MULTIPLE_FACES: "more than one face in view",
    Outcome.POOR_LIGHT: "the lighting is too poor to see your face",
    Outcome.POOR_QUALITY: "the picture was too blurry or too far away",
    Outcome.CAMERA_ERROR: "the camera isn't available",
    Outcome.NOT_ENROLLED: "no face is enrolled (run drivion --enroll-face)",
    Outcome.MODELS_MISSING: "the face models are missing (run drivion --download-models)",
    Outcome.CANCELLED: "verification was cancelled",
}


@dataclass(frozen=True)
class VerifySettings:
    threshold: float
    required_matches: int = 3
    max_unknown: int = 6
    timeout_s: float = 8.0
    limits: QualityLimits = QualityLimits()


@dataclass
class VerificationResult:
    outcome: Outcome
    best_score: float | None = None
    matches: int = 0
    unknown: int = 0
    frames: int = 0
    issues: Counter = field(default_factory=Counter)

    @property
    def verified(self) -> bool:
        return self.outcome is Outcome.MATCH

    @property
    def reason(self) -> str:
        return REASONS[self.outcome]


@dataclass(frozen=True)
class FrameReport:
    issue: FrameIssue
    score: float | None  # None when the frame wasn't good enough to compare
    matched: bool


def _final_outcome(result: VerificationResult) -> Outcome:
    if result.unknown:
        return Outcome.UNKNOWN_FACE
    issues = result.issues
    if not issues:
        return Outcome.NO_FACE
    main, _ = issues.most_common(1)[0]
    return {
        FrameIssue.MULTIPLE_FACES: Outcome.MULTIPLE_FACES,
        FrameIssue.TOO_DARK: Outcome.POOR_LIGHT,
        FrameIssue.TOO_BRIGHT: Outcome.POOR_LIGHT,
        FrameIssue.NO_FACE: Outcome.NO_FACE,
    }.get(main, Outcome.POOR_QUALITY)


def verify(
    source: FrameSource,
    analyzer: FaceAnalyzer,
    templates: np.ndarray,
    settings: VerifySettings,
    stop_event: threading.Event | None = None,
    on_frame: Callable[[np.ndarray, FrameReport], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> VerificationResult:
    """Read frames from an already-open source until a decision is reached."""
    result = VerificationResult(Outcome.NO_FACE)
    deadline = clock() + settings.timeout_s
    while clock() < deadline:
        if stop_event is not None and stop_event.is_set():
            result.outcome = Outcome.CANCELLED
            return result
        try:
            frame = source.read()
        except CameraError:
            result.outcome = Outcome.CAMERA_ERROR
            return result
        if frame is None:
            break
        result.frames += 1
        faces = analyzer.detect(frame)
        issue = assess(frame, faces, settings.limits)
        score = None
        matched = False
        if issue is FrameIssue.OK:
            score = best_similarity(analyzer.embed(frame, faces[0]), templates)
            result.best_score = score if result.best_score is None else max(result.best_score, score)
            matched = score >= settings.threshold
            if matched:
                result.matches += 1
            else:
                result.unknown += 1
        else:
            result.issues[issue] += 1
        if on_frame is not None:
            on_frame(frame, FrameReport(issue, score, matched))

        if result.matches >= settings.required_matches and result.matches > result.unknown:
            result.outcome = Outcome.MATCH
            return result
        if result.unknown >= settings.max_unknown:
            result.outcome = Outcome.UNKNOWN_FACE
            return result
    result.outcome = _final_outcome(result)
    return result


# ----- enrollment -------------------------------------------------------------------------


@dataclass(frozen=True)
class EnrollSettings:
    samples: int = 8
    min_interval_s: float = 0.35     # spread samples out so they aren't near-duplicates
    consistency_min: float = 0.5     # each sample must resemble the others (same person)
    limits: QualityLimits = QualityLimits()


@dataclass(frozen=True)
class EnrollStep:
    issue: FrameIssue
    accepted: bool
    count: int
    note: str = ""
    faces: tuple = ()  # what was detected, so the preview needn't detect again


class Enrollment:
    """Collects consistent, good-quality samples of one face."""

    def __init__(self, analyzer: FaceAnalyzer, settings: EnrollSettings = EnrollSettings(),
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._analyzer = analyzer
        self.settings = settings
        self._clock = clock
        self.embeddings: list[np.ndarray] = []
        self.crops: list[np.ndarray] = []
        self._last_accepted = -1e9

    @property
    def done(self) -> bool:
        return len(self.embeddings) >= self.settings.samples

    def add(self, frame: np.ndarray, keep_crop: bool = False) -> EnrollStep:
        faces = tuple(self._analyzer.detect(frame))
        issue = assess(frame, list(faces), self.settings.limits)
        count = len(self.embeddings)
        if issue is not FrameIssue.OK or self.done:
            return EnrollStep(issue, False, count, faces=faces)
        now = self._clock()
        if now - self._last_accepted < self.settings.min_interval_s:
            return EnrollStep(issue, False, count, faces=faces)
        embedding = self._analyzer.embed(frame, faces[0])
        if self.embeddings:
            centre = np.mean(self.embeddings, axis=0)
            centre /= np.linalg.norm(centre) or 1.0
            if similarity(embedding, centre) < self.settings.consistency_min:
                return EnrollStep(issue, False, count,
                                  "That didn't look like the same face. Only you should be in view.",
                                  faces=faces)
        self.embeddings.append(embedding)
        if keep_crop and hasattr(self._analyzer, "aligned_crop"):
            self.crops.append(self._analyzer.aligned_crop(frame, faces[0]))
        self._last_accepted = now
        return EnrollStep(issue, True, len(self.embeddings), faces=faces)

    def self_similarity(self) -> tuple[float, float]:
        """(min, median) similarity between pairs of your own samples."""
        vectors = np.stack(self.embeddings)
        scores = vectors @ vectors.T
        pairs = scores[np.triu_indices(len(vectors), k=1)]
        return float(pairs.min()), float(np.median(pairs))
