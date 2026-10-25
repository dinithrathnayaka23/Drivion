"""Events that subsystems report to the controller.

Subsystems never change the state directly. They describe *what happened*
("wake word heard", "face verified") and the controller decides what that
means in the current state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EventType(StrEnum):
    WAKE_WORD_DETECTED = "WAKE_WORD_DETECTED"
    ACTIVATION_REQUESTED = "ACTIVATION_REQUESTED"  # tray click / second launch
    VERIFICATION_SUCCEEDED = "VERIFICATION_SUCCEEDED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    SLEEP_REQUESTED = "SLEEP_REQUESTED"            # "Drivion, go to sleep"
    COMMAND_TIMEOUT = "COMMAND_TIMEOUT"            # no speech for a while when active
    FAILURE = "FAILURE"                            # a subsystem crashed
    RECOVER_REQUESTED = "RECOVER_REQUESTED"
    EXIT_REQUESTED = "EXIT_REQUESTED"


@dataclass(frozen=True)
class Event:
    type: EventType
    source: str
    detail: str = ""
    # Verification results must name the attempt they belong to, so a late
    # answer from an earlier, timed-out attempt can't unlock a newer one.
    attempt: int | None = None
