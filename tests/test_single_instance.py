import subprocess
import sys
import uuid

import pytest

from drivion.core.single_instance import (
    ActivationServer,
    SingleInstanceLock,
    notify_running_instance,
)

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows named mutex")


@pytest.fixture
def name():
    return f"DrivionTest-{uuid.uuid4().hex}"


def test_first_lock_acquires_second_is_refused(name):
    with SingleInstanceLock(name) as first:
        assert first.acquired
        with SingleInstanceLock(name) as second:
            assert not second.acquired


def test_lock_is_reusable_after_release(name):
    first = SingleInstanceLock(name)
    assert first.acquire()
    first.release()
    second = SingleInstanceLock(name)
    assert second.acquire()
    second.release()


def test_different_names_do_not_conflict(name):
    with SingleInstanceLock(name) as a, SingleInstanceLock(name + "-other") as b:
        assert a.acquired and b.acquired


def test_release_is_idempotent(name):
    lock = SingleInstanceLock(name)
    lock.acquire()
    lock.release()
    lock.release()
    assert not lock.acquired


CLIENT_SCRIPT = (
    "import sys\n"
    "from PySide6.QtCore import QCoreApplication\n"
    "from drivion.core.single_instance import notify_running_instance\n"
    "app = QCoreApplication(sys.argv)\n"
    "sys.exit(0 if notify_running_instance(sys.argv[1]) else 1)\n"
)


def test_second_launch_can_ask_running_instance_to_open(qtbot, name):
    server = ActivationServer(name)
    assert server.listen()
    # The client runs in its own process, exactly like a second Drivion launch.
    # (Qt sockets must not be used from plain Python threads.)
    client = subprocess.Popen([sys.executable, "-c", CLIENT_SCRIPT, name])
    try:
        with qtbot.waitSignal(server.activation_requested, timeout=10000):
            pass
        assert client.wait(10) == 0
    finally:
        client.kill()
        server.close()


def test_notify_returns_false_when_nothing_is_running(qapp, name):
    assert notify_running_instance(name, timeout_ms=200) is False
