import hashlib
import io

import pytest

from drivion.audio import models
from drivion.audio.models import ModelDownloadError, ModelFile, download_models, is_valid

GOOD = b"pretend onnx model"
SPEC = ModelFile("test.onnx", "https://example.invalid/test.onnx", hashlib.sha256(GOOD).hexdigest())


class FakeUrlopen:
    def __init__(self, payload=GOOD, error=None):
        self.payload, self.error, self.calls = payload, error, []

    def __call__(self, url, timeout):
        self.calls.append(url)
        if self.error:
            raise self.error
        return io.BytesIO(self.payload)


def test_download_verifies_and_saves(tmp_path, monkeypatch):
    fake = FakeUrlopen()
    monkeypatch.setattr(models.urllib.request, "urlopen", fake)
    written = download_models(tmp_path / "m", [SPEC])
    assert written == [tmp_path / "m" / "test.onnx"]
    assert is_valid(tmp_path / "m", SPEC)
    assert not list((tmp_path / "m").glob("*.part"))


def test_tampered_download_is_rejected_and_not_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(models.urllib.request, "urlopen", FakeUrlopen(payload=b"evil"))
    with pytest.raises(ModelDownloadError, match="integrity check"):
        download_models(tmp_path, [SPEC])
    assert list(tmp_path.iterdir()) == []


def test_network_error_leaves_nothing_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(models.urllib.request, "urlopen", FakeUrlopen(error=OSError("offline")))
    with pytest.raises(ModelDownloadError, match="offline"):
        download_models(tmp_path, [SPEC])
    assert list(tmp_path.iterdir()) == []


def test_valid_existing_file_is_not_downloaded_again(tmp_path, monkeypatch):
    (tmp_path / "test.onnx").write_bytes(GOOD)
    fake = FakeUrlopen()
    monkeypatch.setattr(models.urllib.request, "urlopen", fake)
    assert download_models(tmp_path, [SPEC]) == []
    assert fake.calls == []


def test_corrupted_existing_file_is_replaced(tmp_path, monkeypatch):
    (tmp_path / "test.onnx").write_bytes(b"truncated")
    monkeypatch.setattr(models.urllib.request, "urlopen", FakeUrlopen())
    download_models(tmp_path, [SPEC])
    assert is_valid(tmp_path, SPEC)


def test_every_pinned_model_uses_https_and_a_full_hash():
    for spec in models.DOWNLOADABLE:
        assert spec.url.startswith("https://")
        assert len(spec.sha256) == 64
