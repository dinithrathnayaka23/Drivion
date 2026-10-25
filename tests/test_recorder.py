import numpy as np
import pytest

from drivion.speech.recorder import RecorderEvent, RecorderSettings, UtteranceRecorder

FRAME = 1024  # 64 ms
SETTINGS = RecorderSettings(speech_threshold=0.5, min_speech_s=0.2, end_silence_s=0.8,
                            max_utterance_s=3.0, pre_roll_s=0.3)


def frame(value):
    return np.full(FRAME, value, dtype=np.int16)


def feed(recorder, probabilities, start_value=0):
    """Push frames whose sample value is their index, so we can see which were kept."""
    events = []
    for i, p in enumerate(probabilities):
        event = recorder.push(frame(start_value + i), p)
        if event:
            events.append((i, event))
    return events


@pytest.fixture
def recorder():
    return UtteranceRecorder(SETTINGS, FRAME)


def test_silence_never_starts(recorder):
    assert feed(recorder, [0.0] * 100) == []
    assert not recorder.is_speaking


def test_short_click_is_ignored(recorder):
    # 0.2 s minimum = 4 frames; a 2-frame click shouldn't count.
    assert feed(recorder, [0.0, 0.9, 0.9, 0.0, 0.0]) == []


def test_command_is_captured_with_pre_roll(recorder):
    probs = [0.0] * 10 + [0.9] * 20 + [0.0] * 13  # 13 silent frames = 0.83 s
    events = feed(recorder, probs)
    assert events == [(13, RecorderEvent.STARTED), (42, RecorderEvent.FINISHED)]
    audio = recorder.utterance.audio
    first_kept = audio[0]
    # Speech began at frame 10; ~0.3 s (5 frames) of pre-roll is kept before it.
    assert 4 <= first_kept <= 6
    assert not recorder.utterance.truncated


def test_brief_pause_inside_a_command_does_not_end_it(recorder):
    probs = [0.9] * 6 + [0.0] * 5 + [0.9] * 6 + [0.0] * 13
    events = feed(recorder, probs)
    assert [e for _, e in events] == [RecorderEvent.STARTED, RecorderEvent.FINISHED]
    assert recorder.utterance.duration_s > 1.5


def test_long_speech_is_cut_at_the_limit(recorder):
    events = feed(recorder, [0.9] * 200)
    assert events[-1][1] is RecorderEvent.FINISHED
    assert recorder.utterance.truncated
    assert recorder.utterance.duration_s <= SETTINGS.max_utterance_s + 0.4


def test_reset_discards_partial_speech(recorder):
    feed(recorder, [0.9] * 6)
    assert recorder.is_speaking
    recorder.reset()
    assert not recorder.is_speaking
    assert recorder.utterance is None


def test_finished_utterance_is_kept_until_reset(recorder):
    feed(recorder, [0.9] * 10 + [0.0] * 13)
    finished = recorder.utterance
    assert finished is not None
    assert feed(recorder, [0.9] * 20) == []  # ignored, not a second recording
    assert recorder.utterance is finished
    recorder.reset()
    assert feed(recorder, [0.9] * 5)[0][1] is RecorderEvent.STARTED
