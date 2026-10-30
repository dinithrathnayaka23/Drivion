"""Synthetic frames, faces and embeddings: face logic without a camera or real faces."""

from __future__ import annotations

import numpy as np

from drivion.vision.camera import CameraError
from drivion.vision.quality import Face

DIM = 128
OWNER = np.zeros(DIM, dtype=np.float32)
OWNER[0] = 1.0


def embedding(similarity_to_owner: float, salt: int = 1) -> np.ndarray:
    """A unit vector with an exact cosine similarity to OWNER."""
    other = np.zeros(DIM, dtype=np.float32)
    other[salt] = 1.0
    sin = float(np.sqrt(max(0.0, 1 - similarity_to_owner ** 2)))
    return (similarity_to_owner * OWNER + sin * other).astype(np.float32)


def frame(brightness: int = 130, sharp: bool = True, seed: int = 0) -> np.ndarray:
    """A 480x640 BGR frame; sharp = textured (high Laplacian variance), else flat."""
    rng = np.random.default_rng(seed)
    if sharp:
        base = rng.integers(brightness - 40, brightness + 40, size=(480, 640), dtype=np.int16)
    else:
        base = np.full((480, 640), brightness, dtype=np.int16)
    return np.repeat(np.clip(base, 0, 255).astype(np.uint8)[..., None], 3, axis=2)


def face(x=200, y=120, size=200, yaw=0.0) -> Face:
    """A detected face; yaw shifts the nose sideways (relative to eye distance)."""
    eye_l, eye_r = np.array([x + size * 0.7, y + size * 0.4]), np.array([x + size * 0.3, y + size * 0.4])
    eye_distance = float(np.linalg.norm(eye_l - eye_r))
    nose = np.array([x + size * 0.5 + yaw * eye_distance, y + size * 0.6])
    landmarks = np.array([eye_r, eye_l, nose, [x + size * 0.35, y + size * 0.8],
                          [x + size * 0.65, y + size * 0.8]], dtype=np.float32)
    return Face((x, y, size, size), landmarks, 0.95, np.zeros(15, dtype=np.float32))


class Shot:
    """One scripted camera frame: the picture, the faces in it, and their embedding."""

    def __init__(self, picture=None, faces=None, similarity=None):
        self.picture = frame() if picture is None else picture
        self.faces = [face()] if faces is None else faces
        self.embedding = embedding(similarity) if similarity is not None else embedding(0.0)


def me(similarity=0.9):
    return Shot(similarity=similarity)


def stranger(similarity=0.2):
    return Shot(similarity=similarity)


def nobody():
    return Shot(faces=[])


def crowd():
    return Shot(faces=[face(50), face(350)], similarity=0.9)


def dark():
    return Shot(picture=frame(brightness=25), similarity=0.9)


class FakeCamera:
    """Plays scripted shots; reports what the analyzer should 'see' via ``current``."""

    def __init__(self, shots, fail_open=False, fail_after=None, endless=False):
        self.shots = list(shots)
        self.fail_open, self.fail_after, self.endless = fail_open, fail_after, endless
        self.opened = self.closed = False
        self.reads = 0
        self.current: Shot | None = None

    def open(self):
        if self.fail_open:
            raise CameraError("camera in use (fake)")
        self.opened = True

    def read(self):
        if self.fail_after is not None and self.reads >= self.fail_after:
            raise CameraError("camera unplugged (fake)")
        self.reads += 1
        if self.shots:
            self.current = self.shots.pop(0)
        elif self.endless:
            self.current = nobody()
        else:
            return None
        return self.current.picture

    def close(self):
        self.closed = True


class FakeAnalyzer:
    model_id = "fake-recognizer"

    def __init__(self, camera: FakeCamera):
        self.camera = camera
        self.detections = 0

    def detect(self, picture):
        self.detections += 1
        return list(self.camera.current.faces)

    def embed(self, picture, detected):
        return self.camera.current.embedding

    def aligned_crop(self, picture, detected):
        return np.zeros((112, 112, 3), dtype=np.uint8)


def owner_templates(n=5):
    return np.stack([embedding(0.97, salt=2 + i) for i in range(n)])
