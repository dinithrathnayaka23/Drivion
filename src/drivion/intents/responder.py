"""Decides what Drivion says (and does) for each recognised command.

``AssistantResponder`` plugs into ``CommandProcessor`` in place of the
Milestone 5 echo. It parses the transcript, then:

* built-ins work now: help, repeat, cancel, go to sleep;
* system commands (volume, apps, power, ...) are understood and validated,
  but only acknowledged - Milestone 7 adds the safety-checked actions;
* questions are acknowledged until an AI provider exists (Milestone 8).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from drivion.core.activity import Outcome
from drivion.intents import schemas as s
from drivion.intents.catalog import Catalog
from drivion.intents.parser import IntentParser, Invalid, NotUnderstood, Understood

log = logging.getLogger(__name__)

NOT_UNDERSTOOD_REPLY = "Sorry, I don't know how to do that yet. Say “help” to hear what I can do."
NOTHING_TO_REPEAT = "I haven't said anything yet."
NOTHING_TO_CANCEL = "There's nothing to cancel."
NOTHING_TO_CONFIRM = "There's nothing waiting for a yes or no."
QUESTION_REPLY = "I can't answer questions yet. That needs an AI provider, which isn't set up."


class AssistantResponder:
    """Callable ``text -> (reply, outcome)``; safe to call from any thread."""

    def __init__(
        self,
        catalog: Catalog,
        on_go_to_sleep: Callable[[], None],
        wake_phrase: str,
    ) -> None:
        self._catalog = catalog
        self._parser = IntentParser(catalog)
        self._on_go_to_sleep = on_go_to_sleep
        self._wake_phrase = wake_phrase
        self._last_reply: str | None = None
        self._lock = threading.Lock()

    def __call__(self, text: str) -> tuple[str, Outcome]:
        result = self._parser.parse(text)
        log.info("Parsed %r -> %s", text, _summary(result))
        reply, outcome = self._respond(result)
        if not isinstance(getattr(result, "intent", None), s.Repeat):
            with self._lock:
                self._last_reply = reply
        return reply, outcome

    def _respond(self, result) -> tuple[str, Outcome]:
        if isinstance(result, NotUnderstood):
            return NOT_UNDERSTOOD_REPLY, Outcome.REJECTED
        if isinstance(result, Invalid):
            return result.reason, Outcome.REJECTED

        intent = result.intent
        match intent:
            case s.Help():
                return self._help(), Outcome.SUCCESS
            case s.Repeat():
                with self._lock:
                    last = self._last_reply
                return (last, Outcome.SUCCESS) if last else (NOTHING_TO_REPEAT, Outcome.SUCCESS)
            case s.Cancel():
                return NOTHING_TO_CANCEL, Outcome.SUCCESS
            case s.Confirm() | s.Deny():
                return NOTHING_TO_CONFIRM, Outcome.REJECTED
            case s.Greet():
                return "Yes? What would you like me to do?", Outcome.SUCCESS
            case s.GoToSleep():
                self._on_go_to_sleep()
                return f"Going to sleep. Say “{self._wake_phrase}” when you need me.", Outcome.SUCCESS
            case s.AskQuestion():
                return QUESTION_REPLY, Outcome.REJECTED
        what = s.describe(intent, self._name_for)
        return f"I understood: {what}. I can't control the computer yet.", Outcome.REJECTED

    def _name_for(self, target_id: str) -> str:
        aliases = self._catalog.apps.get(target_id)
        return aliases[0] if aliases else target_id.replace("_", " ")

    def _help(self) -> str:
        examples = [self._name_for(app_id) for app_id in list(self._catalog.apps)[:2]]
        example_app = " or ".join(examples) or "an app"
        return (
            f"You can say things like: open {example_app}, set the volume to 50 percent, "
            "turn the brightness down, take a screenshot, or lock the computer. "
            "Say repeat to hear my last answer, or go to sleep when you're done. "
            "For now I understand those commands but can't carry out the computer ones yet."
        )


def _summary(result) -> str:
    if isinstance(result, Understood):
        return result.intent.model_dump_json()
    if isinstance(result, Invalid):
        return f"invalid ({result.reason})"
    return "not understood"
