"""Head-turn liveness, with scripted head poses (no camera, no real faces)."""

import threading
from collections import Counter

import numpy as np
import pytest

import face_fakes as ff
from drivion.core.activity import DeviceState
from drivion.vision.liveness import (
    LOOK_AHEAD,
    PROMPTS,
    Challenge,
    LivenessOutcome,
    LivenessSettings,
    pick_challenges,
    run_challenges,
)
from drivion.vision.quality import signed_yaw
from drivion.vision.service import FaceVerificationService
from drivion.vision.templates import FaceTemplates, TemplateStore
from drivion.vision.verification import Outcome, VerifySettings

SETTINGS = LivenessSettings(threshold=0.55, hold_frames=2, baseline_frames=3, max_lost_frames=4)
LEFT, RIGHT = Challenge.TURN_LEFT, Challenge.TURN_RIGHT


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 0.05
        return self.now


def pose(yaw=0.0, x=200, similarity=0.9):
    return ff.Shot(faces=[ff.face(x=x, yaw=yaw)], similarity=similarity)


def centred(n=4):
    return [pose() for _ in range(n)]


def turned(yaw, n=3):
    return [pose(yaw) for _ in range(n)]


def run(shots, challenges=(LEFT,), settings=SETTINGS, **camera_kw):
    camera = ff.FakeCamera(shots, **camera_kw)
    prompts = []
    result = run_challenges(camera, ff.FakeAnalyzer(camera), ff.owner_templates(), settings,
                            list(challenges), prompts.append, clock=Clock())
    return result, prompts


def test_yaw_sign():
    assert signed_yaw(ff.face(yaw=0.4)) == pytest.approx(0.4, abs=0.01)
    assert signed_yaw(ff.face(yaw=-0.4)) == pytest.approx(-0.4, abs=0.01)


def test_following_the_prompts_passes():
    shots = centred() + turned(0.45) + centred() + turned(-0.45) + centred()
    result, prompts = run(shots, (LEFT, RIGHT))
    assert result.passed and result.completed == 2
    assert prompts == [PROMPTS[LEFT], PROMPTS[RIGHT], LOOK_AHEAD]


def test_a_still_photo_times_out():
    result, _ = run([pose() for _ in range(500)])
    assert result.outcome is LivenessOutcome.TIMED_OUT and not result.passed


def test_a_tilted_photo_does_not_count_as_a_turn():
    # On real detector output tilting a photo moved yaw by at most 0.126.
    wobble = [pose(0.126 * ((i % 2) * 2 - 1)) for i in range(500)]
    result, _ = run(centred() + wobble)
    assert result.outcome is LivenessOutcome.TIMED_OUT


def test_turning_the_wrong_way_fails_at_once():
    result, _ = run(centred() + turned(-0.45))
    assert result.outcome is LivenessOutcome.WRONG_WAY


def test_a_single_noisy_frame_is_not_a_turn():
    shots = centred() + [pose(0.45)] + centred(200)
    result, _ = run(shots)
    assert not result.passed


def test_a_second_face_fails():
    result, _ = run(centred() + [ff.crowd()] + turned(0.45) + centred())
    assert result.outcome is LivenessOutcome.MULTIPLE_FACES


def test_swapping_the_picture_is_seen_as_a_jump():
    result, _ = run(centred() + [pose(0.45, x=420)] + turned(0.45) + centred())
    assert result.outcome is LivenessOutcome.FACE_CHANGED


def test_losing_the_face_for_too_long_fails():
    result, _ = run(centred() + [ff.nobody()] * 6)
    assert result.outcome is LivenessOutcome.FACE_LOST


def test_a_short_loss_during_a_turn_is_fine():
    shots = centred() + turned(0.45, 1) + [ff.nobody()] * 2 + turned(0.45) + centred()
    assert run(shots)[0].passed


def test_someone_else_finishing_the_check_fails():
    last = [pose(similarity=0.1) for _ in range(500)]
    result, _ = run(centred() + turned(0.45) + last)
    assert result.outcome is LivenessOutcome.FACE_CHANGED


def test_never_looking_back_fails():
    result, _ = run(centred() + turned(0.45, 500))
    assert result.outcome is LivenessOutcome.TIMED_OUT


def test_a_person_who_starts_turned_is_measured_from_there():
    assert run(turned(0.2, 4) + turned(0.55) + turned(0.2, 4))[0].passed


def test_mirrored_camera_swaps_the_directions():
    mirrored = LivenessSettings(threshold=0.55, max_lost_frames=4, mirrored=True)
    assert run(centred() + turned(-0.45) + centred(), settings=mirrored)[0].passed


def test_camera_failure_and_cancel_fail_closed():
    assert run([], fail_after=0)[0].outcome is LivenessOutcome.CAMERA_ERROR
    camera = ff.FakeCamera([], endless=True)
    stop = threading.Event()
    stop.set()
    result = run_challenges(camera, ff.FakeAnalyzer(camera), ff.owner_templates(), SETTINGS,
                            [LEFT], lambda t: None, stop)
    assert result.outcome is LivenessOutcome.CANCELLED


def test_challenges_are_random_and_cover_both_directions():
    counts = Counter(c for _ in range(200) for c in pick_challenges(2))
    assert counts[LEFT] > 120 and counts[RIGHT] > 120


# ----- within face verification ---------------------------------------------------------


def service_run(tmp_path, shots, challenges=(LEFT,)):
    import drivion.vision.service as service_module

    store = TemplateStore(tmp_path / "face")
    store.save(FaceTemplates(ff.owner_templates(), "fake-recognizer"))
    camera = ff.FakeCamera(shots)
    results, prompts, done = [], [], threading.Event()
    original = service_module.pick_challenges
    service_module.pick_challenges = lambda count: list(challenges)
    try:
        service = FaceVerificationService(
            lambda: camera, lambda: ff.FakeAnalyzer(camera), store,
            VerifySettings(threshold=0.55, timeout_s=5), lambda: 1,
            lambda attempt, result: (results.append(result), done.set()),
            lambda state: None, liveness=SETTINGS, on_prompt=prompts.append)
        service.start()
        assert done.wait(10)
        service.stop()
    finally:
        service_module.pick_challenges = original
    return results[0], prompts


def test_face_match_plus_liveness_unlocks(tmp_path):
    shots = [ff.me()] * 3 + centred() + turned(0.45) + centred()
    result, prompts = service_run(tmp_path, shots)
    assert result.verified and prompts[0] == PROMPTS[LEFT]


def test_face_match_without_liveness_is_denied_with_the_reason(tmp_path):
    result, _ = service_run(tmp_path, [ff.me()] * 3 + centred() + turned(-0.45))
    assert not result.verified and result.outcome is Outcome.NOT_LIVE
    assert result.reason == "the head turned the wrong way"


def test_a_stranger_never_reaches_the_challenges(tmp_path):
    result, prompts = service_run(tmp_path, [ff.stranger()] * 10)
    assert result.outcome is Outcome.UNKNOWN_FACE and prompts == []


def test_attempt_budget_covers_every_step():
    from drivion.config.settings import FaceSettings

    face = FaceSettings()
    assert face.total_timeout_s == 10 + (2 * 2 + 2) * 6
    assert FaceSettings(liveness_mode="none").total_timeout_s == 10


def test_blink_mode_was_removed():
    from drivion.config.settings import FaceSettings

    with pytest.raises(ValueError):
        FaceSettings(liveness_mode="blink")
