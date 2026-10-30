"""Face detection (YuNet) and recognition (SFace), both built into OpenCV.

* **YuNet** finds faces and five landmarks (eyes, nose, mouth corners).
* **SFace** aligns a detected face and turns it into a 128-number embedding.
  Two embeddings of the same person point in similar directions, so their
  *cosine similarity* is high; for different people it is low.

Both are small ONNX models from OpenCV's model zoo, downloaded and
hash-checked by ``drivion --download-models``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np

from drivion.audio.models import ModelFile, is_valid
from drivion.vision.quality import Face

_ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models"

YUNET = ModelFile(
    "face_detection_yunet_2023mar.onnx",
    f"{_ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
)
SFACE = ModelFile(
    "face_recognition_sface_2021dec.onnx",
    f"{_ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
    "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
)
FACE_MODELS = [YUNET, SFACE]
RECOGNIZER_ID = "sface_2021dec"  # stored with templates; a different model means re-enrolling


class FaceModelsUnavailable(Exception):
    pass


class FaceAnalyzer(Protocol):
    model_id: str

    def detect(self, frame_bgr: np.ndarray) -> list[Face]: ...

    def embed(self, frame_bgr: np.ndarray, face: Face) -> np.ndarray:
        """128-d, L2-normalised embedding of an aligned face."""


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two L2-normalised embeddings (-1..1, higher = more alike)."""
    return float(np.dot(a, b))


def best_similarity(embedding: np.ndarray, templates: np.ndarray) -> float:
    return float(np.max(templates @ embedding))


class OpenCVFaceAnalyzer:
    model_id = RECOGNIZER_ID

    def __init__(self, models_dir: Path, detect_threshold: float = 0.8) -> None:
        broken = [m.filename for m in FACE_MODELS if not is_valid(models_dir, m)]
        if broken:
            raise FaceModelsUnavailable(f"Missing or invalid face models: {', '.join(broken)}. "
                                        "Run `drivion --download-models`.")
        import cv2

        self._cv2 = cv2
        self._detector = cv2.FaceDetectorYN.create(str(models_dir / YUNET.filename), "", (320, 320),
                                                   detect_threshold, 0.3, 5000)
        self._recognizer = cv2.FaceRecognizerSF.create(str(models_dir / SFACE.filename), "")

    def detect(self, frame_bgr: np.ndarray) -> list[Face]:
        height, width = frame_bgr.shape[:2]
        self._detector.setInputSize((width, height))
        _, rows = self._detector.detect(frame_bgr)
        if rows is None:
            return []
        faces = []
        for row in rows:
            x, y, w, h = (int(round(v)) for v in row[:4])
            faces.append(Face((x, y, w, h), row[4:14].reshape(5, 2).astype(np.float32),
                              float(row[14]), row.copy()))
        return faces

    def embed(self, frame_bgr: np.ndarray, face: Face) -> np.ndarray:
        aligned = self._recognizer.alignCrop(frame_bgr, face.raw)
        feature = self._recognizer.feature(aligned).flatten().astype(np.float32)
        norm = float(np.linalg.norm(feature))
        return feature / norm if norm > 0 else feature

    def aligned_crop(self, frame_bgr: np.ndarray, face: Face) -> np.ndarray:
        return self._recognizer.alignCrop(frame_bgr, face.raw)
