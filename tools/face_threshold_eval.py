"""Measure SFace match scores on a public face dataset to choose a threshold.

Dataset: the ORL / "AT&T Database of Faces" (Olivetti Research Laboratory,
Cambridge, 1992-1994): 400 greyscale photos, 10 each of 40 people, varying
lighting, expression and glasses. Credit: Olivetti Research Laboratory.
Download att_faces.zip from
https://www.cl.cam.ac.uk/research/dtg/attarchive/facedatabase.html and
extract it anywhere; nothing is added to this repository.

Protocol (mimics Drivion): for each person, the first ``ENROLL`` photos are
the enrolled templates and the rest are verification attempts. A *genuine*
score compares an attempt with the same person's templates; an *impostor*
score compares it with every other person's templates. The score is the
best cosine similarity over the templates, exactly as in verification.

Usage:  python tools/face_threshold_eval.py <models-dir> <att_faces-dir>
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ENROLL = 5


def load_faces(root: Path):
    import cv2

    images, targets = [], []
    for folder in sorted(root.rglob("s*")):
        if not folder.is_dir() or not folder.name[1:].isdigit():
            continue
        for path in sorted(folder.glob("*.pgm"), key=lambda p: int(p.stem)):
            images.append(cv2.imread(str(path), cv2.IMREAD_GRAYSCALE))
            targets.append(int(folder.name[1:]))
    return images, np.array(targets)


def to_bgr_scene(image: np.ndarray) -> np.ndarray:
    """92x112 greyscale photo -> larger 3-channel frame with margin, like a webcam frame."""
    import cv2

    face = cv2.resize(image, (184, 224), interpolation=cv2.INTER_CUBIC)
    scene = np.full((320, 320), int(np.median(image)), dtype=np.uint8)
    scene[48:272, 68:252] = face
    return cv2.cvtColor(scene, cv2.COLOR_GRAY2BGR)


def embed_all(models_dir: Path, images: np.ndarray):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from drivion.vision.faces import OpenCVFaceAnalyzer

    analyzer = OpenCVFaceAnalyzer(models_dir, detect_threshold=0.6)
    embeddings, found = [], []
    for image in images:
        frame = to_bgr_scene(image)
        faces = analyzer.detect(frame)
        if faces:
            embeddings.append(analyzer.embed(frame, max(faces, key=lambda f: f.score)))
            found.append(True)
        else:
            embeddings.append(None)
            found.append(False)
    return embeddings, np.array(found)


def scores(embeddings, targets):
    people = np.unique(targets)
    templates = {}
    for person in people:
        idx = np.where(targets == person)[0]
        vecs = [embeddings[i] for i in idx[:ENROLL] if embeddings[i] is not None]
        templates[person] = np.stack(vecs) if vecs else None
    genuine, impostor = [], []
    for i, emb in enumerate(embeddings):
        person = targets[i]
        if emb is None or i in np.where(targets == person)[0][:ENROLL]:
            continue
        for other, tpl in templates.items():
            if tpl is None:
                continue
            best = float(np.max(tpl @ emb))
            (genuine if other == person else impostor).append(best)
    return np.array(genuine), np.array(impostor)


def main(models_dir: str, dataset_dir: str) -> None:
    images, targets = load_faces(Path(dataset_dir))
    print(f"Loaded {len(images)} photos of {len(np.unique(targets))} people")
    embeddings, found = embed_all(Path(models_dir), images)
    print(f"Faces detected: {found.sum()}/{len(found)}")
    genuine, impostor = scores(embeddings, targets)
    print(f"Genuine attempts: {len(genuine)}, impostor attempts: {len(impostor)}")
    print(f"Genuine scores:  min {genuine.min():.3f}  5th pct {np.percentile(genuine, 5):.3f}  "
          f"median {np.median(genuine):.3f}")
    print(f"Impostor scores: max {impostor.max():.3f}  99.9th pct {np.percentile(impostor, 99.9):.3f}  "
          f"median {np.median(impostor):.3f}")
    print("\nthreshold   false accepts (impostor >= t)   false rejects (genuine < t)")
    for t in (0.30, 0.363, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70):
        far = (impostor >= t).mean()
        frr = (genuine < t).mean()
        print(f"  {t:.3f}      {far:8.4%} ({(impostor >= t).sum():4d})            "
              f"{frr:8.4%} ({(genuine < t).sum():3d})")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
