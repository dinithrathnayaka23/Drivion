import threading

import pytest

from drivion.core.state import (
    ALLOWED_TRANSITIONS,
    AppState,
    InvalidTransitionError,
    StateMachine,
)

ALL_PAIRS = [(a, b) for a in AppState for b in AppState]


def machine_in(state: AppState) -> StateMachine:
    machine = StateMachine()
    machine._state = state  # test helper: jump straight to a state
    return machine


def test_starts_in_standby():
    assert StateMachine().state is AppState.STANDBY


@pytest.mark.parametrize("current, target", ALL_PAIRS)
def test_every_transition_follows_the_table(current, target):
    machine = machine_in(current)
    if target in ALLOWED_TRANSITIONS[current]:
        assert machine.can_transition(target)
        record = machine.transition(target, "test")
        assert (record.old, record.new) == (current, target)
        assert machine.state is target
    else:
        assert not machine.can_transition(target)
        with pytest.raises(InvalidTransitionError):
            machine.transition(target)
        assert machine.state is current  # rejected moves change nothing


def test_every_state_has_rules():
    assert set(ALLOWED_TRANSITIONS) == set(AppState)


def test_shutting_down_is_terminal():
    assert ALLOWED_TRANSITIONS[AppState.SHUTTING_DOWN] == frozenset()


def test_every_live_state_can_shut_down():
    for state in AppState:
        if state is not AppState.SHUTTING_DOWN:
            assert AppState.SHUTTING_DOWN in ALLOWED_TRANSITIONS[state]


def test_cannot_skip_verification():
    with pytest.raises(InvalidTransitionError):
        StateMachine().transition(AppState.ACTIVE)


def test_listeners_receive_transitions_and_bad_listener_is_isolated():
    machine = StateMachine()
    seen = []

    def broken(_):
        raise RuntimeError("listener bug")

    machine.add_listener(broken)
    machine.add_listener(seen.append)
    machine.transition(AppState.VERIFYING, "wake")
    assert [(t.old, t.new, t.reason) for t in seen] == [
        (AppState.STANDBY, AppState.VERIFYING, "wake")
    ]


def test_concurrent_transitions_only_one_wins():
    for _ in range(200):
        machine = StateMachine()
        barrier = threading.Barrier(4)
        results = []

        def attempt():
            barrier.wait()
            try:
                machine.transition(AppState.VERIFYING)
                results.append("ok")
            except InvalidTransitionError:
                results.append("rejected")

        threads = [threading.Thread(target=attempt) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert results.count("ok") == 1
        assert machine.state is AppState.VERIFYING
