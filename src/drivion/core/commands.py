"""What happens to a recognised command.

``CommandProcessor`` records the command in the activity feed, asks a
*responder* what to do, records the outcome and speaks the reply. The
responder (``intents.responder.AssistantResponder``) parses the command;
the processor doesn't know or care how.
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
