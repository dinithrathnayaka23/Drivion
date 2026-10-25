import threading

import pytest

from drivion.core.activity import ActivityFeed, Device, DeviceState, Outcome


@pytest.fixture
def feed(qapp):
    return ActivityFeed(history_limit=3)


def test_devices_start_off(feed):
    for device in Device:
        assert feed.device_state(device) is DeviceState.OFF


def test_device_change_emits_once(feed, qtbot):
    seen = []
    feed.device_changed.connect(lambda d, s: seen.append((d, s)))
    feed.set_device(Device.CAMERA, DeviceState.ACTIVE)
    feed.set_device(Device.CAMERA, DeviceState.ACTIVE)  # no change -> no signal
    assert seen == [(Device.CAMERA, DeviceState.ACTIVE)]
    assert feed.device_state(Device.CAMERA) is DeviceState.ACTIVE


def test_command_lifecycle(feed):
    added, updated = [], []
    feed.record_added.connect(added.append)
    feed.record_updated.connect(updated.append)

    record_id = feed.add_command("open chrome")
    assert added[0].outcome is Outcome.PENDING
    assert added[0].command == "open chrome"

    feed.complete_command(record_id, "Chrome opened.", Outcome.SUCCESS)
    assert updated[0].id == record_id
    assert updated[0].response == "Chrome opened."
    assert feed.history[0].outcome is Outcome.SUCCESS


def test_ids_are_unique(feed):
    ids = {feed.add_command(f"c{i}") for i in range(10)}
    assert len(ids) == 10


def test_history_is_bounded_and_oldest_is_dropped(feed):
    for i in range(5):
        feed.add_command(f"command {i}")
    assert [r.command for r in feed.history] == ["command 2", "command 3", "command 4"]


def test_completing_an_evicted_record_is_harmless(feed):
    first = feed.add_command("old")
    for i in range(3):
        feed.add_command(f"new {i}")
    updated = []
    feed.record_updated.connect(updated.append)
    feed.complete_command(first, "late", Outcome.SUCCESS)
    assert updated == []


def test_clear_history(feed, qtbot):
    feed.add_command("open chrome")
    with qtbot.waitSignal(feed.history_cleared, timeout=500):
        feed.clear_history()
    assert feed.history == []


def test_updates_from_background_thread_arrive_on_main_thread(feed, qtbot):
    delivered_on = []
    feed.record_added.connect(lambda _: delivered_on.append(threading.current_thread()))
    feed.device_changed.connect(lambda *_: delivered_on.append(threading.current_thread()))

    def worker():
        feed.set_device(Device.MICROPHONE, DeviceState.ACTIVE)
        feed.add_command("from worker")

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    qtbot.waitUntil(lambda: len(delivered_on) == 2, timeout=1000)
    assert delivered_on == [threading.main_thread()] * 2
    assert feed.device_state(Device.MICROPHONE) is DeviceState.ACTIVE


def test_voice_status_changes_are_signalled_once(feed):
    from drivion.core.activity import VoiceStatus

    seen = []
    feed.voice_status_changed.connect(seen.append)
    feed.set_voice_status(VoiceStatus.LISTENING)
    feed.set_voice_status(VoiceStatus.LISTENING)
    feed.set_voice_status(VoiceStatus.HEARING)
    assert seen == [VoiceStatus.LISTENING, VoiceStatus.HEARING]
    assert feed.voice_status is VoiceStatus.HEARING
