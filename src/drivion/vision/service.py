"""Runs face verification while Drivion is VERIFYING.

The service starts when the controller enters VERIFYING (after the wake
word or "Open Drivion") and is stopped when it leaves, which closes the
camera. It reports the result as VERIFICATION_SUCCEEDED / _FAILED tagged
with the attempt id it was started for, so a late answer can never unlock
a newer attempt (the controller checks this).

It finishes a little before the controller's own timeout so it can say
*why* it failed ("too dark", "no face") instead of a bare timeout.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from drivion.core.activity import DeviceState
from drivion.core.services import ThreadedService
from drivion.vision.camera import CameraError, FrameSource
from drivion.vision.faces import FaceAnalyzer, FaceModelsUnavailable
from drivion.vision.liveness import (
    LivenessOutcome,
    LivenessSettings,
    pick_challenges,
    run_challenges,
)
from drivion.vision.templates import TemplateError, TemplateStore
from drivion.vision.verification import Outcome, VerificationResult, VerifySettings, verify

log = logging.getLogger(__name__)

# Report before the controller's timeout fires, so the reason isn't lost.
REPORT_MARGIN_S = 1.5


class FaceVerificationService(ThreadedService):
    def __init__(
        self,
        source_factory: Callable[[], FrameSource],
        analyzer_factory: Callable[[], FaceAnalyzer],
        store: TemplateStore,
        settings: VerifySettings,
        current_attempt: Callable[[], int | None],
        on_result: Callable[[int, VerificationResult], None],
        on_camera: Callable[[DeviceState], None],
        liveness: LivenessSettings | None = None,  # None = face match only
        on_prompt: Callable[[str], None] = lambda text: None,
    ) -> None:
        super().__init__("face-verification")
        self._liveness = liveness
        self._on_prompt = on_prompt
        self._source_factory = source_factory
        self._analyzer_factory = analyzer_factory
        self._analyzer: FaceAnalyzer | None = None  # loaded once, reused
        self._store = store
        self._settings = settings
        self._current_attempt = current_attempt
        self._on_result = on_result
        self._on_camera = on_camera
        self._source: FrameSource | None = None
        self._camera_failed = False

    def run(self, stop_event: threading.Event) -> None:
        attempt = self._current_attempt()
        if attempt is None:
            return  # no verification in progress (e.g. already left VERIFYING)
        self._camera_failed = False
        result = self._attempt(stop_event)
        if result.outcome is Outcome.CANCELLED:
            return  # Drivion left VERIFYING; nobody is waiting for this answer
        log.info("Face verification attempt %d: %s (best score %s, %d matching of %d frames)",
                 attempt, result.outcome, f"{result.best_score:.3f}" if result.best_score else "-",
                 result.matches, result.frames)
        self._on_result(attempt, result)

    def _attempt(self, stop_event: threading.Event) -> VerificationResult:
        try:
            if self._analyzer is None:
                self._analyzer = self._analyzer_factory()
        except FaceModelsUnavailable as exc:
            log.warning("Face verification unavailable: %s", exc)
            return VerificationResult(Outcome.MODELS_MISSING)
        try:
            templates = self._store.load(self._analyzer.model_id).embeddings
        except TemplateError as exc:
            log.warning("Face verification unavailable: %s", exc)
            return VerificationResult(Outcome.NOT_ENROLLED)

        self._source = self._source_factory()
        try:
            self._source.open()
        except CameraError as exc:
            log.warning("%s", exc)
            self._camera_failed = True
            return VerificationResult(Outcome.CAMERA_ERROR)
        self._on_camera(DeviceState.ACTIVE)
        result = verify(self._source, self._analyzer, templates, self._settings, stop_event)
        if result.verified and self._liveness is not None:
            self._check_liveness(result, templates, stop_event)
        self._camera_failed = result.outcome is Outcome.CAMERA_ERROR
        return result

    def _check_liveness(self, result: VerificationResult, templates, stop_event) -> None:
        """A face match only counts once the liveness challenges pass too."""
        check = run_challenges(self._source, self._analyzer, templates, self._liveness,
                               pick_challenges(self._liveness.challenges), self._on_prompt,
                               stop_event)
        log.info("Liveness: %s after %d of %d challenges", check.outcome, check.completed,
                 self._liveness.challenges)
        if check.outcome is LivenessOutcome.CANCELLED:
            result.outcome = Outcome.CANCELLED
        elif check.outcome is LivenessOutcome.CAMERA_ERROR:
            result.outcome = Outcome.CAMERA_ERROR
        elif not check.passed:
            result.outcome, result.detail = Outcome.NOT_LIVE, check.reason

    def cleanup(self) -> None:
        source, self._source = self._source, None
        if source is not None:
            source.close()
            self._on_camera(DeviceState.ERROR if self._camera_failed else DeviceState.OFF)
        elif self._camera_failed:
            self._on_camera(DeviceState.ERROR)
