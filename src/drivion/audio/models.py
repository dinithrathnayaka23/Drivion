"""Wake-word model files: where they live and how they are downloaded.

Drivion never downloads anything on its own. Models are fetched only when
you run ``drivion --download-models``. Each file is checked against a pinned
SHA-256 hash, so a corrupted or tampered download is rejected instead of
being loaded.

Files are stored per user in ``%LOCALAPPDATA%\\Drivion\\models``, outside
the repository.
"""

from __future__ import annotations

import hashlib
import logging
import urllib.request
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_RELEASE = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1"


@dataclass(frozen=True)
class ModelFile:
    filename: str
    url: str
    sha256: str


# Feature extractors shared by every openWakeWord model.
MELSPECTROGRAM = ModelFile(
    "melspectrogram.onnx", f"{_RELEASE}/melspectrogram.onnx",
    "ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f",
)
EMBEDDING = ModelFile(
    "embedding_model.onnx", f"{_RELEASE}/embedding_model.onnx",
    "70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f",
)

# Pre-trained wake words that can be selected by name in the config.
# (model file, phrase shown in the UI). Pre-trained openWakeWord models are
# licensed CC BY-NC-SA 4.0: fine for personal use, not for commercial use.
BUILTIN_WAKE_WORDS: dict[str, tuple[ModelFile, str]] = {
    "hey_jarvis": (
        ModelFile(
            "hey_jarvis_v0.1.onnx", f"{_RELEASE}/hey_jarvis_v0.1.onnx",
            "94a13cfe60075b132f6a472e7e462e8123ee70861bc3fb58434a73712ee0d2cb",
        ),
        "Hey Jarvis",
    ),
}

DOWNLOADABLE: list[ModelFile] = [MELSPECTROGRAM, EMBEDDING] + [
    model for model, _ in BUILTIN_WAKE_WORDS.values()
]


class ModelDownloadError(Exception):
    pass


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_valid(directory: Path, model: ModelFile) -> bool:
    path = directory / model.filename
    return path.is_file() and sha256_of(path) == model.sha256


def download_models(directory: Path, models: list[ModelFile] = DOWNLOADABLE,
                    timeout_s: float = 30.0) -> list[Path]:
    """Download any missing or invalid models. Returns the files written."""
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for model in models:
        target = directory / model.filename
        if is_valid(directory, model):
            log.info("Model %s already present and verified", model.filename)
            continue
        log.info("Downloading %s", model.url)
        partial = target.with_suffix(target.suffix + ".part")
        try:
            with urllib.request.urlopen(model.url, timeout=timeout_s) as response:
                partial.write_bytes(response.read())
        except OSError as exc:
            partial.unlink(missing_ok=True)
            raise ModelDownloadError(f"Could not download {model.filename}: {exc}") from exc

        actual = sha256_of(partial)
        if actual != model.sha256:
            partial.unlink(missing_ok=True)
            raise ModelDownloadError(
                f"{model.filename} failed its integrity check "
                f"(expected {model.sha256[:12]}…, got {actual[:12]}…); nothing was saved"
            )
        partial.replace(target)  # atomic: never leaves a half-written model
        written.append(target)
    return written
