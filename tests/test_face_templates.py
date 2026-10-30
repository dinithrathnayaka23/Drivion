"""Encrypted face template storage (Windows DPAPI)."""

import sys

import numpy as np
import pytest

import face_fakes as ff
from drivion.vision.templates import FaceTemplates, TemplateError, TemplateStore

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI")


@pytest.fixture
def store(tmp_path):
    return TemplateStore(tmp_path / "face")


def save_owner(store, model="fake-recognizer"):
    store.save(FaceTemplates(ff.owner_templates(), model, self_similarity_min=0.9,
                             self_similarity_median=0.95))



@windows_only
def test_templates_round_trip_encrypted(store):
    save_owner(store)
    loaded = store.load("fake-recognizer")
    np.testing.assert_allclose(loaded.embeddings, ff.owner_templates())
    assert loaded.self_similarity_median == 0.95


@windows_only
def test_file_on_disk_is_not_readable(store):
    save_owner(store)
    raw = store.path.read_bytes()
    assert b"embeddings" not in raw and b"fake-recognizer" not in raw  # no plaintext JSON
    assert ff.owner_templates().tobytes()[:32] not in raw


@windows_only
def test_no_photos_are_stored_unless_asked(store):
    save_owner(store)
    assert sorted(p.name for p in store.directory.iterdir()) == ["templates.bin"]
    store.save(FaceTemplates(ff.owner_templates(), "m"), crops=[np.zeros((112, 112, 3), np.uint8)])
    assert store.crops_path.exists()  # only with store_raw_images = true
    save_owner(store)
    assert not store.crops_path.exists()  # re-enrolling without it removes old crops


@windows_only
def test_tampered_or_foreign_files_are_rejected(store):
    save_owner(store)
    data = bytearray(store.path.read_bytes())
    data[80] ^= 0xFF
    store.path.write_bytes(bytes(data))
    with pytest.raises(TemplateError):
        store.load("fake-recognizer")


@windows_only
def test_templates_from_another_model_must_be_re_enrolled(store):
    save_owner(store, model="old-model")
    with pytest.raises(TemplateError, match="different model"):
        store.load("fake-recognizer")


def test_missing_templates(store):
    assert not store.exists()
    with pytest.raises(TemplateError, match="--enroll-face"):
        store.load("fake-recognizer")


@windows_only
def test_delete_removes_everything(store):
    store.save(FaceTemplates(ff.owner_templates(), "m"), crops=[np.zeros((112, 112, 3), np.uint8)])
    assert store.delete() is True
    assert list(store.directory.iterdir()) == []
    assert store.delete() is False


def test_face_data_lives_outside_the_repository():
    from pathlib import Path

    from drivion.config import paths

    repo = Path(__file__).resolve().parents[1]
    assert repo not in paths.face_dir().resolve().parents
