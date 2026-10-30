"""Face verification and enrollment decisions, with scripted frames (no camera, no real faces)."""

import threading

import numpy as np
import pytest

import face_fakes as ff
from drivion.vision.quality import FrameIssue, QualityLimits, assess
from drivion.vision.verification import (
    EnrollSettings,
    Enrollment,
    Outcome,
    VerifySettings,
    verify,
)

SETTINGS = VerifySettings(threshold=0.55, required_matches=3, max_unknown=6, timeout_s=8.0)


class Clock:
    def __init__(self, step=0.1):
        self.now, self.step = 0.0, step

    def __call__(self):
        self.now += self.step
        return self.now


def run(shots, settings=SETTINGS, **camera_kw):
    camera = ff.FakeCamera(shots, **camera_kw)
    camera.open()
    analyzer = ff.FakeAnalyzer(camera)
    return verify(camera, analyzer, ff.owner_templates(), settings, clock=Clock()), camera


# ----- frame quality ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "picture, faces, issue",
    [
        (ff.frame(), [ff.face()], FrameIssue.OK),
        (ff.frame(), [], FrameIssue.NO_FACE),
        (ff.frame(brightness=10), [], FrameIssue.TOO_DARK),          # can't even find a face
        (ff.frame(), [ff.face(50), ff.face(350)], FrameIssue.MULTIPLE_FACES),
        (ff.frame(), [ff.face(size=60)], FrameIssue.TOO_SMALL),
        (ff.frame(brightness=30), [ff.face()], FrameIssue.TOO_DARK),
        (ff.frame(brightness=240), [ff.face()], FrameIssue.TOO_BRIGHT),
        (ff.frame(sharp=False), [ff.face()], FrameIssue.BLURRY),
        (ff.frame(), [ff.face(yaw=0.6)], FrameIssue.NOT_FRONTAL),
    ],
)
def test_frame_quality(picture, faces, issue):
    assert assess(picture, faces, QualityLimits()) is issue


# ----- verification -------------------------------------------------------------------------


def test_owner_is_verified_after_three_matching_frames():
    result, camera = run([ff.me()] * 10)
    assert result.outcome is Outcome.MATCH and result.verified
    assert result.matches == 3 and result.frames == 3  # stops as soon as it's sure
    assert result.best_score == pytest.approx(0.9 * 0.97, abs=0.05)


def test_stranger_is_rejected_quickly():
    result, _ = run([ff.stranger()] * 50)
    assert result.outcome is Outcome.UNKNOWN_FACE and not result.verified
    assert result.frames == 6  # doesn't get to keep trying until the timeout


def test_lookalike_just_below_threshold_is_rejected():
    result, _ = run([ff.stranger(similarity=0.5)] * 50)  # 0.5 * 0.97 < 0.55
    assert result.outcome is Outcome.UNKNOWN_FACE


def test_a_few_lucky_frames_do_not_beat_mostly_unknown_ones():
    shots = [ff.stranger()] * 4 + [ff.me()] * 3 + [ff.stranger()] * 10
    result, _ = run(shots)
    assert not result.verified  # 3 matches but 4 unknowns: matches must be the majority


def test_poor_frames_neither_help_nor_hurt():
    shots = [ff.dark(), ff.nobody(), ff.crowd(), ff.dark(), ff.me(), ff.me(), ff.me()]
    result, _ = run(shots)
    assert result.verified
    assert result.unknown == 0  # bad lighting never counted as "unknown face"


@pytest.mark.parametrize(
    "shots, outcome",
    [
        ([ff.dark()] * 200, Outcome.POOR_LIGHT),
        ([ff.nobody()] * 200, Outcome.NO_FACE),
        ([ff.crowd()] * 200, Outcome.MULTIPLE_FACES),
        ([ff.Shot(faces=[ff.face(size=50)], similarity=0.9)] * 200, Outcome.POOR_QUALITY),
    ],
)
def test_timeout_names_the_main_problem(shots, outcome):
    result, _ = run(shots)
    assert result.outcome is outcome and not result.verified


def test_two_people_in_view_is_never_a_match():
    result, _ = run([ff.crowd()] * 200)  # the owner is one of them, but it's not accepted
    assert not result.verified


def test_camera_failure_fails_closed():
    result, _ = run([ff.me()] * 10, fail_after=1)
    assert result.outcome is Outcome.CAMERA_ERROR and not result.verified


def test_stop_cancels_without_a_verdict():
    camera = ff.FakeCamera([], endless=True)
    camera.open()
    stop = threading.Event()
    stop.set()
    result = verify(camera, ff.FakeAnalyzer(camera), ff.owner_templates(), SETTINGS, stop)
    assert result.outcome is Outcome.CANCELLED and not result.verified


def test_stricter_settings_need_more_matches():
    strict = VerifySettings(threshold=0.55, required_matches=6, timeout_s=8)
    result, _ = run([ff.me()] * 5, settings=strict)
    assert not result.verified


# ----- enrollment --------------------------------------------------------------------------


class StepClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 0.5
        return self.now


def enroll(shots, settings=EnrollSettings(samples=4)):
    camera = ff.FakeCamera(shots)
    enrollment = Enrollment(ff.FakeAnalyzer(camera), settings, clock=StepClock())
    steps = []
    while not enrollment.done:
        picture = camera.read()
        if picture is None:
            break
        steps.append(enrollment.add(picture))
    return enrollment, steps


def test_enrollment_collects_good_samples_only():
    shots = [ff.nobody(), ff.dark(), ff.me(0.95), ff.crowd(), ff.me(0.96), ff.me(0.97), ff.me(0.95)]
    enrollment, steps = enroll(shots)
    assert enrollment.done and len(enrollment.embeddings) == 4
    assert [s.accepted for s in steps] == [False, False, True, False, True, True, True]
    assert steps[1].issue is FrameIssue.TOO_DARK


def test_enrollment_rejects_a_different_person_stepping_in():
    enrollment, steps = enroll([ff.me(0.95), ff.stranger(0.1), ff.me(0.96), ff.me(0.95), ff.me(0.97)])
    assert not steps[1].accepted and "same face" in steps[1].note
    assert enrollment.done


def test_samples_are_spread_out_in_time():
    camera = ff.FakeCamera([ff.me()] * 10)
    clock_value = [0.0]
    enrollment = Enrollment(ff.FakeAnalyzer(camera), EnrollSettings(samples=3, min_interval_s=1.0),
                            clock=lambda: clock_value[0])
    for _ in range(5):  # five frames at the same instant: only one may count
        enrollment.add(camera.read())
    assert len(enrollment.embeddings) == 1


def test_self_similarity_summary():
    enrollment, _ = enroll([ff.me(0.95)] * 4)
    low, median = enrollment.self_similarity()
    assert 0 <= low <= median <= 1
