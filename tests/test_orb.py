from PySide6.QtGui import QColor

from drivion.core.state import AppState
from drivion.ui.theme import STATE_COLORS
from drivion.ui.widgets.orb import StateOrb


def make_orb(qtbot, animated=True):
    orb = StateOrb(animated=animated)
    qtbot.addWidget(orb)
    return orb


def test_animation_runs_only_while_visible(qtbot):
    orb = make_orb(qtbot)
    assert not orb.is_animating  # hidden widgets cost no CPU
    orb.show()
    assert orb.is_animating
    orb.hide()
    assert not orb.is_animating


def test_reduced_motion_never_starts_timer(qtbot):
    orb = make_orb(qtbot, animated=False)
    orb.show()
    assert not orb.is_animating


def test_color_transitions_smoothly_to_state_color(qtbot):
    orb = make_orb(qtbot)
    orb.show()
    orb.set_state(AppState.ERROR)
    target = QColor(STATE_COLORS[AppState.ERROR])
    assert orb.color != target  # mid-transition right after the change
    qtbot.waitUntil(lambda: orb.color == target, timeout=2000)


def test_hidden_or_static_orb_switches_color_immediately(qtbot):
    orb = make_orb(qtbot)
    orb.set_state(AppState.VERIFYING)  # not visible -> no animation needed
    assert orb.color == QColor(STATE_COLORS[AppState.VERIFYING])

    static = make_orb(qtbot, animated=False)
    static.show()
    static.set_state(AppState.ACTIVE)
    assert static.color == QColor(STATE_COLORS[AppState.ACTIVE])


def test_paints_every_state_without_error(qtbot):
    orb = make_orb(qtbot)
    orb.resize(300, 300)
    orb.show()
    for state in AppState:
        orb.set_state(state)
        assert not orb.grab().isNull()
