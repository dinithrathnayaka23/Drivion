"""The real OpenCV face models (YuNet + SFace).

* Always (once `drivion --download-models` has run): the models load and a
  picture with no face in it is seen as "no face".
* With ``DRIVION_FACE_DATASET`` pointing at the extracted ORL / AT&T face
  database (see tools/face_threshold_eval.py): the default threshold is
  checked on 40 real people, and full verification runs end to end on real
  photos. The photos aren't part of this repository.
"""

import os
import sys
from pathlib import Path

import numpy as np
import pytest

from drivion.config.settings import FaceSettings
from drivion.vision.faces import FACE_MODELS, OpenCVFaceAnalyzer

MODELS = Path(os.environ.get("LOCALAPPDATA", "")) / "Drivion" / "models"
DATASET = os.environ.get("DRIVION_FACE_DATASET")
TOOLS = Path(__file__).resolve().parents[1] / "tools"

pytestmark = pytest.mark.skipif(
    not all((MODELS / m.filename).exists() for m in FACE_MODELS),
    reason="run `drivion --download-models`",
)
needs_dataset = pytest.mark.skipif(not DATASET, reason="set DRIVION_FACE_DATASET to the ORL faces folder")


@pytest.fixture(scope="module")
def analyzer():
    return OpenCVFaceAnalyzer(MODELS)


def test_models_load_and_find_nothing_in_an_empty_scene(analyzer):
    noise = np.random.default_rng(0).integers(0, 255, size=(480, 640, 3), dtype=np.uint8)
    assert analyzer.detect(noise) == []
    assert analyzer.detect(np.zeros((480, 640, 3), dtype=np.uint8)) == []
    assert analyzer.model_id == "sface_2021dec"


@pytest.fixture(scope="module")
def dataset():
    sys.path.insert(0, str(TOOLS))
    import face_threshold_eval as tool

    images, targets = tool.load_faces(Path(DATASET))
    return tool, images, targets


@needs_dataset
def test_default_threshold_separates_real_people(dataset):
    tool, images, targets = dataset
    embeddings, found = tool.embed_all(MODELS, images)
    genuine, impostor = tool.scores(embeddings, targets)
    threshold = FaceSettings().similarity_threshold
    assert found.mean() > 0.99
    assert (impostor >= threshold).sum() == 0            # no stranger accepted
    assert (genuine < threshold).mean() <= 0.01          # at most 1% of genuine frames rejected


@needs_dataset
def test_end_to_end_verification_on_real_photos(dataset, analyzer):
    from drivion.vision.quality import QualityLimits
    from drivion.vision.verification import VerifySettings, verify

    tool, images, targets = dataset
    frames = {p: [tool.to_bgr_scene(images[i]) for i in np.where(targets == p)[0]] for p in (1, 2, 3)}

    def templates_of(person):
        vecs = []
        for frame in frames[person][:5]:
            faces = analyzer.detect(frame)
            vecs.append(analyzer.embed(frame, faces[0]))
        return np.stack(vecs)

    class Photos:
        def __init__(self, pictures):
            self.pictures = list(pictures)

        def read(self):
            return self.pictures.pop(0) if self.pictures else None

    # The photos are small and greyscale; relax only the size/sharpness limits.
    settings = VerifySettings(threshold=FaceSettings().similarity_threshold, timeout_s=60,
                              limits=QualityLimits(min_face_px=60, min_sharpness=5, min_brightness=30))
    owner = templates_of(1)
    assert verify(Photos(frames[1][5:]), analyzer, owner, settings).verified
    for stranger in (2, 3):
        assert not verify(Photos(frames[stranger]), analyzer, owner, settings).verified


def _tilt_flat(frame, degrees):
    """Perspective view of a flat picture rotated about its vertical axis."""
    import cv2

    h, w = frame.shape[:2]
    angle = np.radians(degrees)
    focal = 1.2 * w
    source = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    target = []
    for x, y in source - [w / 2, h / 2]:
        depth = x * np.sin(angle) + focal
        target.append([x * np.cos(angle) * focal / depth + w / 2, y * focal / depth + h / 2])
    matrix = cv2.getPerspectiveTransform(source, np.float32(target))
    return cv2.warpPerspective(frame, matrix, (w, h), borderValue=(128, 128, 128))


@needs_dataset
def test_tilting_a_real_photo_never_passes_liveness(dataset, analyzer):
    from drivion.vision.liveness import Challenge, LivenessSettings, run_challenges
    from drivion.vision.quality import QualityLimits

    tool, images, targets = dataset
    settings = LivenessSettings(threshold=FaceSettings().similarity_threshold,
                                limits=QualityLimits(min_face_px=60, min_sharpness=5, min_brightness=30))
    for index in np.where(targets == 1)[0][:5]:
        frame = tool.to_bgr_scene(images[index])
        templates = analyzer.embed(frame, analyzer.detect(frame)[0])[None, :]

        class TiltedPhoto:
            def __init__(self):
                self.sweep = [0, 0, 0, 0, 20, 35, 50, 50, 35, 20, 0, -20, -35, -50, -50, -35, -20] * 8

            def read(self):
                return _tilt_flat(frame, self.sweep.pop(0)) if self.sweep else None

        for challenge in Challenge:
            result = run_challenges(TiltedPhoto(), analyzer, templates, settings, [challenge],
                                    lambda text: None)
            assert not result.passed, result
