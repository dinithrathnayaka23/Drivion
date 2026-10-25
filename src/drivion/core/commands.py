"""What happens to a recognised command.

``CommandProcessor`` records the command in the activity feed, asks a
*responder* what to do, records the outcome and speaks the reply. In
Milestone 5 the responder only echoes what it heard; Milestone 6 replaces
it with real intent parsing, without changing anything else.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from drivion.core.activity import ActivityFeed, Outcome
from drivion.speech.tts import Speaker

log = logging.getLogger(__name__)

Responder = Callable[[str], tuple[str, Outcome]]

UNCLEAR_REPLY = "Sorry, I didn't catch that."
ERROR_REPLY = "Sorry, something went wrong with that command."


def echo_responder(text: str) -> tuple[str, Outcome]:
    """Milestone 5 placeholder: confirm what was heard, act on nothing."""
    heard = text.strip().rstrip(".!?")
    return f"I heard: {heard}. I can't carry out commands yet.", Outcome.REJECTED


class CommandProcessor:
    def __init__(self, feed: ActivityFeed, speaker: Speaker, responder: Responder) -> None:
        self._feed = feed
        self._speaker = speaker
        self._responder = responder

    def handle(self, text: str) -> None:
        """Called from the listener thread; the feed and speaker are thread-safe."""
        record_id = self._feed.add_command(text)
        try:
            reply, outcome = self._responder(text)
        except Exception:
            log.exception("Responder failed for %r", text)
            reply, outcome = ERROR_REPLY, Outcome.FAILED
        self._feed.complete_command(record_id, reply, outcome)
        self._speaker.say(reply)

    def unclear(self) -> None:
        self._speaker.say(UNCLEAR_REPLY)
