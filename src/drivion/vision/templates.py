"""Encrypted, local storage for face templates.

What is stored is a handful of 128-number *embeddings* (SFace feature
vectors), not photos. An embedding can't be turned back into a picture of
your face, but it is still biometric data, so the file is encrypted with
**Windows DPAPI** (CryptProtectData). Only your Windows account on this
computer can decrypt it; a copied file is useless elsewhere.

Location: ``%LOCALAPPDATA%\\Drivion\\face\\templates.bin`` - outside the
repository, so it can't be committed by accident. Raw enrollment crops are
only kept if ``face.store_raw_images = true``, and then encrypted the same way.
"""

from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import sys
from ctypes import wintypes as wt
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

FORMAT_VERSION = 1
_ENTROPY = b"Drivion face templates v1"  # extra input to DPAPI: binds the blob to this purpose


class TemplateError(Exception):
    """Templates are missing, unreadable, or were made by a different model."""


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> tuple[_Blob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _dpapi(data: bytes, protect: bool) -> bytes:
    if sys.platform != "win32":
        raise TemplateError("Face templates are encrypted with Windows DPAPI (Windows only)")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    data_in, keep_in = _blob(data)
    entropy, keep_entropy = _blob(_ENTROPY)
    data_out = _Blob()
    function = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = function(ctypes.byref(data_in), None, ctypes.byref(entropy), None, None, 0x1,  # UI_FORBIDDEN
                  ctypes.byref(data_out))
    if not ok:
        raise TemplateError(f"Windows couldn't {'encrypt' if protect else 'decrypt'} the face data "
                            f"(error {ctypes.get_last_error()})")
    try:
        return ctypes.string_at(data_out.pbData, data_out.cbData)
    finally:
        kernel32.LocalFree(data_out.pbData)


def protect(data: bytes) -> bytes:
    return _dpapi(data, protect=True)


def unprotect(data: bytes) -> bytes:
    return _dpapi(data, protect=False)


@dataclass
class FaceTemplates:
    embeddings: np.ndarray            # N x 128, float32, L2-normalised
    model: str                        # recognizer that produced them (must match at verify time)
    created: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    # Similarity between your own enrollment samples (for threshold guidance).
    self_similarity_min: float | None = None
    self_similarity_median: float | None = None


class TemplateStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / "templates.bin"
        self.crops_path = directory / "enrollment_crops.bin"

    def exists(self) -> bool:
        return self.path.is_file()

    def save(self, templates: FaceTemplates, crops: list[np.ndarray] | None = None) -> None:
        payload = {
            "version": FORMAT_VERSION,
            "model": templates.model,
            "created": templates.created,
            "self_similarity_min": templates.self_similarity_min,
            "self_similarity_median": templates.self_similarity_median,
            "embeddings": base64.b64encode(templates.embeddings.astype(np.float32).tobytes()).decode(),
            "dim": int(templates.embeddings.shape[1]),
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.path, protect(json.dumps(payload).encode("utf-8")))
        if crops:
            stacked = np.stack(crops).astype(np.uint8)
            raw = json.dumps({"shape": stacked.shape, "data": base64.b64encode(stacked.tobytes()).decode()})
            _atomic_write(self.crops_path, protect(raw.encode("utf-8")))
        elif self.crops_path.exists():
            self.crops_path.unlink()
        log.info("Saved %d face templates (encrypted) to %s", len(templates.embeddings), self.path)

    def load(self, expected_model: str) -> FaceTemplates:
        if not self.exists():
            raise TemplateError("No face is enrolled yet. Run `drivion --enroll-face`.")
        try:
            payload = json.loads(unprotect(self.path.read_bytes()))
            dim = int(payload["dim"])
            vectors = np.frombuffer(base64.b64decode(payload["embeddings"]), dtype=np.float32)
            embeddings = vectors.reshape(-1, dim).copy()
        except TemplateError:
            raise
        except Exception as exc:
            raise TemplateError("The face data is damaged. Enroll again with `drivion --enroll-face`.") from exc
        if payload.get("version") != FORMAT_VERSION or payload.get("model") != expected_model:
            raise TemplateError("The face data was made by a different model version. "
                                "Enroll again with `drivion --enroll-face`.")
        return FaceTemplates(embeddings, payload["model"], payload["created"],
                             payload.get("self_similarity_min"), payload.get("self_similarity_median"))

    def delete(self) -> bool:
        """Remove all stored face data. Returns True if anything was deleted."""
        removed = False
        for path in (self.path, self.crops_path):
            if path.exists():
                _overwrite_and_remove(path)
                removed = True
        return removed


def _atomic_write(path: Path, data: bytes) -> None:
    partial = path.with_suffix(path.suffix + ".part")
    partial.write_bytes(data)
    os.replace(partial, path)


def _overwrite_and_remove(path: Path) -> None:
    # Best effort: SSDs may keep old copies, but at least the file content is gone.
    try:
        path.write_bytes(os.urandom(path.stat().st_size))
    finally:
        path.unlink()
