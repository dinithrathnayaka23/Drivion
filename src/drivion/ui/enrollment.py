"""Face enrollment (``drivion --enroll-face``) and testing (``drivion --test-face``).

Enrollment asks for explicit consent first, shows a live preview with
guidance ("too dark", "move closer"), and saves only encrypted embeddings.
Test mode shows your live match score against the threshold, so you can
check the threshold for your own camera and lighting. The preview is shown
on screen only and never saved.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import numpy as np
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from drivion.ui import theme
from drivion.vision.camera import CameraError, FrameSource
from drivion.vision.faces import FaceAnalyzer, FaceModelsUnavailable, best_similarity
from drivion.vision.liveness import LivenessSettings, pick_challenges, run_challenges
from drivion.vision.quality import GUIDANCE, FrameIssue, assess, signed_yaw
from drivion.vision.templates import FaceTemplates, TemplateError, TemplateStore
from drivion.vision.verification import EnrollSettings, Enrollment

log = logging.getLogger(__name__)

CONSENT_TEXT = """\
<b>Drivion will use your camera to learn your face.</b><br><br>
• The camera turns on only while this window is open and when Drivion verifies you.<br>
• Drivion stores <b>face templates</b> (lists of numbers describing your face), not photos{photos}.<br>
• They are <b>encrypted with your Windows account</b> and stay on this computer, in
  <code>%LOCALAPPDATA%\\Drivion\\face</code>. Nothing is uploaded.<br>
• You can delete them at any time with <code>drivion --delete-face</code>.<br>
• Face matching on a normal webcam can be fooled by a good photo or video of you. Drivion
  only protects its own features; it never replaces your Windows sign-in.<br><br>
Only you should be in front of the camera. Look straight at it in good, even light."""


def to_qimage(frame_bgr: np.ndarray) -> QImage:
    rgb = np.ascontiguousarray(frame_bgr[:, ::-1, ::-1])  # mirror like a mirror; BGR -> RGB
    height, width = rgb.shape[:2]
    return QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()


def _outline(frame: np.ndarray, faces, good: bool) -> np.ndarray:
    shown = frame.copy()
    colour = np.array((80, 220, 120) if good else (60, 180, 245), dtype=np.uint8)  # BGR
    for face in faces:
        x, y, w, h = face.box
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(shown.shape[1] - 1, x + w), min(shown.shape[0] - 1, y + h)
        shown[y0:y0 + 2, x0:x1] = colour
        shown[y1 - 1:y1 + 1, x0:x1] = colour
        shown[y0:y1, x0:x0 + 2] = colour
        shown[y0:y1, x1 - 1:x1 + 1] = colour
    return shown


class CaptureWorker(QObject):
    """Reads the camera on a background thread and reports to the dialog via signals."""

    frame = Signal(QImage)
    status = Signal(str)
    progress = Signal(int)
    finished = Signal(bool, str)

    def __init__(self, source_factory: Callable[[], FrameSource],
                 analyzer_factory: Callable[[], FaceAnalyzer], store: TemplateStore,
                 mode: str, threshold: float, settings: EnrollSettings, keep_crops: bool,
                 liveness: LivenessSettings | None = None) -> None:
        super().__init__()
        self._source_factory = source_factory
        self._analyzer_factory = analyzer_factory
        self._store = store
        self.mode = mode
        self._threshold = threshold
        self._settings = settings
        self._keep_crops = keep_crops
        self._liveness = liveness
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"face-{self.mode}", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        try:
            analyzer = self._analyzer_factory()
            templates = None
            if self.mode != "enroll":
                templates = self._store.load(analyzer.model_id).embeddings
        except (FaceModelsUnavailable, TemplateError) as exc:
            self.finished.emit(False, str(exc))
            return
        source = self._source_factory()
        try:
            source.open()
        except CameraError as exc:
            self.finished.emit(False, str(exc))
            return
        try:
            if self.mode == "enroll":
                self._enroll(source, analyzer)
            elif self.mode == "liveness":
                self._check_liveness(source, analyzer, templates)
            else:
                self._test(source, analyzer, templates)
        except CameraError as exc:
            self.finished.emit(False, str(exc))
        finally:
            source.close()

    def _enroll(self, source: FrameSource, analyzer: FaceAnalyzer) -> None:
        enrollment = Enrollment(analyzer, self._settings)
        while not self._stop.is_set() and not enrollment.done:
            frame = source.read()
            if frame is None:
                break
            step = enrollment.add(frame, keep_crop=self._keep_crops)
            self.frame.emit(to_qimage(_outline(frame, step.faces, step.issue is FrameIssue.OK)))
            self.status.emit(step.note or GUIDANCE[step.issue])
            self.progress.emit(step.count)
        if self._stop.is_set():
            self.finished.emit(False, "Enrollment cancelled. Nothing was saved.")
            return
        if not enrollment.done:
            self.finished.emit(False, "The camera stopped before enrollment finished. Nothing was saved.")
            return
        low, median = enrollment.self_similarity()
        self._store.save(FaceTemplates(np.stack(enrollment.embeddings), analyzer.model_id,
                                       self_similarity_min=low, self_similarity_median=median),
                         crops=enrollment.crops if self._keep_crops else None)
        message = (f"Done. {len(enrollment.embeddings)} encrypted face templates were saved "
                   f"(consistency: lowest {low:.2f}, typical {median:.2f}).")
        if low < self._threshold + 0.05:
            message += (" Some samples were quite different from each other; if Drivion often fails "
                        "to recognise you, enroll again in better light.")
        self.finished.emit(True, message)

    def _test(self, source: FrameSource, analyzer: FaceAnalyzer, templates: np.ndarray) -> None:
        while not self._stop.is_set():
            frame = source.read()
            if frame is None:
                break
            faces = analyzer.detect(frame)
            issue = assess(frame, faces)
            if issue is FrameIssue.OK:
                score = best_similarity(analyzer.embed(frame, faces[0]), templates)
                verdict = "MATCH" if score >= self._threshold else "no match"
                self.status.emit(f"Score {score:.2f} (threshold {self._threshold:.2f}): {verdict}"
                                 f"   |   turn {signed_yaw(faces[0]):+.2f}")
            else:
                self.status.emit(GUIDANCE[issue])
            self.frame.emit(to_qimage(_outline(frame, faces, issue is FrameIssue.OK)))
        self.finished.emit(True, "Test finished.")


    def _check_liveness(self, source: FrameSource, analyzer: FaceAnalyzer, templates: np.ndarray) -> None:
        def show(frame, faces) -> None:
            self.frame.emit(to_qimage(_outline(frame, faces, len(faces) == 1)))

        result = run_challenges(source, analyzer, templates, self._liveness,
                                pick_challenges(self._liveness.challenges), self.status.emit,
                                self._stop, show)
        self.finished.emit(result.passed, f"Liveness check: {result.reason}.")


class FaceDialog(QDialog):
    def __init__(self, worker: CaptureWorker, already_enrolled: bool, keep_crops: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.worker = worker
        self.succeeded = False
        enroll = worker.mode == "enroll"
        self.setWindowTitle("Drivion - enroll your face" if enroll else "Drivion - test face checks")
        self.setStyleSheet(theme.STYLESHEET + f"QDialog {{ background: {theme.BACKGROUND}; }}")
        self.resize(720, 640)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._consent_page(enroll, already_enrolled, keep_crops))
        self.pages.addWidget(self._capture_page(enroll))
        self.pages.addWidget(self._result_page())
        layout = QVBoxLayout(self)
        layout.addWidget(self.pages)

        worker.frame.connect(lambda image: self.preview.setPixmap(QPixmap.fromImage(image).scaled(
            self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio)))
        worker.status.connect(self.guidance.setText)
        worker.progress.connect(self.progress.setValue)
        worker.finished.connect(self._on_finished)

    # ----- pages ----------------------------------------------------------------------

    def _consent_page(self, enroll: bool, already_enrolled: bool, keep_crops: bool) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        photos = ("; because store_raw_images is on, small aligned face crops are also kept, encrypted"
                  if keep_crops else "")
        text = CONSENT_TEXT.format(photos=photos) if enroll else (
            "<b>Test the head-turn liveness check.</b><br><br>The camera turns on and Drivion asks "
            "you to turn your head. Nothing is saved." if self.worker.mode == "liveness" else
            "<b>Test face recognition.</b><br><br>The camera turns on and shows your live match "
            "score against the threshold, and how far your head is turned. Nothing is saved. "
            "Close the window to stop.")
        if enroll and already_enrolled:
            text += "<br><br><b>This replaces your current enrollment.</b>"
        info = QLabel(text, wordWrap=True, textFormat=Qt.TextFormat.RichText)
        layout.addWidget(info)
        layout.addStretch()
        self.consent = QCheckBox("I agree: use my camera and store encrypted face templates on this computer.")
        self.consent.setVisible(enroll)
        self.start_button = QPushButton("Start" if enroll else "Start test")
        self.start_button.setEnabled(not enroll)  # enrollment needs consent first
        self.consent.toggled.connect(self.start_button.setEnabled)
        self.start_button.clicked.connect(self._start)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self.consent, 1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.start_button)
        layout.addLayout(buttons)
        return page

    def _capture_page(self, enroll: bool) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.camera_on = QLabel("● Camera ON", objectName="deviceChip")
        self.camera_on.setProperty("deviceState", "ACTIVE")
        layout.addWidget(self.camera_on, 0, Qt.AlignmentFlag.AlignRight)
        self.preview = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(480, 360)
        layout.addWidget(self.preview, 1)
        self.guidance = QLabel("Starting the camera…", alignment=Qt.AlignmentFlag.AlignCenter,
                               objectName="listening")
        layout.addWidget(self.guidance)
        self.progress = QProgressBar(maximum=self.worker._settings.samples, value=0)
        self.progress.setVisible(enroll)
        layout.addWidget(self.progress)
        stop = QPushButton("Cancel" if enroll else "Stop")
        stop.clicked.connect(self.reject)
        layout.addWidget(stop, 0, Qt.AlignmentFlag.AlignRight)
        return page

    def _result_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.result = QLabel(wordWrap=True, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        layout.addWidget(self.result)
        layout.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        return page

    # ----- flow -----------------------------------------------------------------------

    def _start(self) -> None:
        self.pages.setCurrentIndex(1)
        self.worker.start()

    def _on_finished(self, ok: bool, message: str) -> None:
        self.succeeded = ok
        self.result.setText(message)
        self.pages.setCurrentIndex(2)

    def done(self, result: int) -> None:  # closing for any reason stops the camera
        self.worker.stop()
        super().done(result)
