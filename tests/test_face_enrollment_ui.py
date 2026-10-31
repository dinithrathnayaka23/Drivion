"""The enrollment / test window and the face commands, with a fake camera."""

import sys

import pytest

import face_fakes as ff
from drivion.ui.enrollment import CaptureWorker, FaceDialog
from drivion.vision.templates import FaceTemplates, TemplateStore
from drivion.vision.verification import EnrollSettings

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI")


def make_dialog(qtbot, tmp_path, mode="enroll", shots=None, store=None, **camera_kw):
    camera = ff.FakeCamera([ff.me(0.95)] * 40 if shots is None else shots, **camera_kw)
    store = store or TemplateStore(tmp_path / "face")
    worker = CaptureWorker(lambda: camera, lambda: ff.FakeAnalyzer(camera), store, mode,
                           threshold=0.55, settings=EnrollSettings(samples=3, min_interval_s=0),
                           keep_crops=False)
    dialog = FaceDialog(worker, already_enrolled=store.exists())
    qtbot.addWidget(dialog)
    return dialog, camera, store


def test_enrollment_cannot_start_without_consent(qtbot, tmp_path):
    dialog, camera, _ = make_dialog(qtbot, tmp_path)
    assert not dialog.start_button.isEnabled()
    dialog.start_button.click()
    assert not camera.opened  # no camera before consent
    dialog.consent.setChecked(True)
    assert dialog.start_button.isEnabled()
    dialog.consent.setChecked(False)
    assert not dialog.start_button.isEnabled()


@windows_only
def test_full_enrollment_saves_encrypted_templates(qtbot, tmp_path):
    dialog, camera, store = make_dialog(qtbot, tmp_path)
    dialog.consent.setChecked(True)
    dialog.start_button.click()
    qtbot.waitUntil(lambda: dialog.pages.currentIndex() == 2, timeout=5000)
    assert dialog.succeeded
    assert "3 encrypted face templates were saved" in dialog.result.text()
    assert store.load("fake-recognizer").embeddings.shape == (3, ff.DIM)
    assert camera.closed  # camera off as soon as it's done
    assert not store.crops_path.exists()  # no photos


def test_cancelling_saves_nothing_and_stops_the_camera(qtbot, tmp_path):
    dialog, camera, store = make_dialog(qtbot, tmp_path, shots=[], endless=True)
    dialog.consent.setChecked(True)
    dialog.start_button.click()
    qtbot.waitUntil(lambda: camera.opened, timeout=3000)
    dialog.reject()
    qtbot.waitUntil(lambda: camera.closed, timeout=3000)
    assert not store.exists()


def test_busy_camera_is_explained(qtbot, tmp_path):
    dialog, _, store = make_dialog(qtbot, tmp_path, fail_open=True)
    dialog.consent.setChecked(True)
    dialog.start_button.click()
    qtbot.waitUntil(lambda: dialog.pages.currentIndex() == 2, timeout=3000)
    assert not dialog.succeeded and "camera in use (fake)" in dialog.result.text()  # error shown as-is
    assert not store.exists()


def test_re_enrolling_warns_that_it_replaces_the_old_face(qtbot, tmp_path):
    store = TemplateStore(tmp_path / "face")
    store.directory.mkdir(parents=True)
    store.path.write_bytes(b"x")  # pretend something is enrolled
    dialog, _, _ = make_dialog(qtbot, tmp_path, store=store)
    assert dialog.consent.isVisibleTo(dialog)
    page_text = dialog.pages.widget(0).findChildren(type(dialog.result))[0].text()
    assert "replaces your current enrollment" in page_text


@windows_only
def test_test_mode_shows_live_scores(qtbot, tmp_path):
    store = TemplateStore(tmp_path / "face")
    store.save(FaceTemplates(ff.owner_templates(), "fake-recognizer"))
    dialog, _, _ = make_dialog(qtbot, tmp_path, mode="test", shots=[ff.me(0.95)] * 3 + [ff.stranger()] * 3,
                               store=store)
    seen = []
    dialog.worker.status.connect(seen.append)
    assert dialog.start_button.isEnabled()  # nothing is stored, so no consent step
    dialog.start_button.click()
    qtbot.waitUntil(lambda: dialog.pages.currentIndex() == 2, timeout=5000)
    assert any("MATCH" in s for s in seen) and any("no match" in s for s in seen)


@windows_only
def test_liveness_mode_runs_the_challenge_with_prompts(qtbot, tmp_path, monkeypatch):
    from drivion.vision.liveness import PROMPTS, Challenge, LivenessSettings

    monkeypatch.setattr("drivion.ui.enrollment.pick_challenges", lambda n: [Challenge.TURN_LEFT])
    store = TemplateStore(tmp_path / "face")
    store.save(FaceTemplates(ff.owner_templates(), "fake-recognizer"))
    centre = [ff.Shot(faces=[ff.face()], similarity=0.9) for _ in range(8)]
    turn = [ff.Shot(faces=[ff.face(yaw=0.45)], similarity=0.9) for _ in range(3)]
    dialog, _, _ = make_dialog(qtbot, tmp_path, mode="liveness", shots=centre[:4] + turn + centre[4:],
                               store=store)
    dialog.worker._liveness = LivenessSettings(threshold=0.55)
    prompts = []
    dialog.worker.status.connect(prompts.append)
    dialog.start_button.click()
    qtbot.waitUntil(lambda: dialog.pages.currentIndex() == 2, timeout=5000)
    assert dialog.succeeded and "passed" in dialog.result.text()
    assert PROMPTS[Challenge.TURN_LEFT] in prompts
