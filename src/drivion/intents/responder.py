"""Decides what Drivion says (and does) for each recognised command.

``AssistantResponder`` plugs into ``CommandProcessor``. It parses the
transcript, then:

* built-ins: help, repeat, greetings and go to sleep;
* system commands go to the ``SafeExecutor``, which runs registered actions
  only, while Drivion is unlocked, and holds high-risk ones for a "yes";
* yes / no / cancel answer a pending confirmation (or abort a scheduled
  restart/shutdown);
* questions are acknowledged until an AI provider exists (Milestone 8).

Without an executor (``executor=None``) system commands are understood but
only acknowledged.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from drivion.core.activity import Outcome
from drivion.intents import schemas as s
from drivion.intents.catalog import Catalog
from drivion.intents.parser import IntentParser, Invalid, NotUnderstood, Understood
from drivion.llm.assistant import Answer, LLMAssistant
from drivion.llm.fallback import AllProvidersFailed
from drivion.safety.executor import NeedsConfirmation, Refused, SafeExecutor

log = logging.getLogger(__name__)

NOT_UNDERSTOOD_REPLY = "Sorry, I don't know how to do that yet. Say “help” to hear what I can do."
NOTHING_TO_REPEAT = "I haven't said anything yet."
NOTHING_TO_CANCEL = "There's nothing to cancel."
NOTHING_TO_CONFIRM = "There's nothing waiting for a yes or no."
QUESTION_REPLY = "I can't answer questions yet. That needs an AI provider, which isn't set up."
NO_AI_KEY_REPLY = ("I can't answer that: no AI service is set up. "
                   "Add an API key to the .env file.")
AI_UNREACHABLE_REPLY = "I couldn't reach any AI service right now. Please try again in a moment."


class AssistantResponder:
    """Callable ``text -> (reply, outcome)``; safe to call from any thread."""

    def __init__(
        self,
        catalog: Catalog,
        on_go_to_sleep: Callable[[], None],
        wake_phrase: str,
        executor: SafeExecutor | None = None,
        cancel_scheduled: Callable[[], str | None] = lambda: None,
        llm: LLMAssistant | None = None,
        on_thinking: Callable[[], None] = lambda: None,
    ) -> None:
        self._catalog = catalog
        self._parser = IntentParser(catalog)
        self._on_go_to_sleep = on_go_to_sleep
        self._wake_phrase = wake_phrase
        self._executor = executor
        self._cancel_scheduled = cancel_scheduled
        self._llm = llm
        self._on_thinking = on_thinking
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

    def name_for(self, target_id: str) -> str:
        return self._catalog.spoken_name(target_id)

    def describe(self, intent: s._Intent) -> str:
        return s.describe(intent, self.name_for)

    # ----- decisions ----------------------------------------------------------------

    def _respond(self, result) -> tuple[str, Outcome]:
        if isinstance(result, NotUnderstood):
            if self._llm is None:
                return self._after_dropping_pending(NOT_UNDERSTOOD_REPLY, Outcome.REJECTED)
            # Never let an unclear reply count as consent, then ask the AI.
            note = self._drop_pending("an unrecognised reply was given")
            reply, outcome = self._ask_ai(result.text)
            return (f"{note} {reply}" if note else reply), outcome
        if isinstance(result, Invalid):
            return self._after_dropping_pending(result.reason, Outcome.REJECTED)

        intent = result.intent
        match intent:
            case s.Repeat():
                with self._lock:
                    last = self._last_reply
                return (last or NOTHING_TO_REPEAT), Outcome.SUCCESS
            case s.Confirm():
                return self._confirm()
            case s.Deny():
                return self._deny()
            case s.Cancel():
                return self._cancel()

        # Any other command means the user moved on: forget a pending action.
        note = self._drop_pending("another command was given")
        reply, outcome = self._handle(intent)
        return (f"{note} {reply}" if note else reply), outcome

    def _handle(self, intent) -> tuple[str, Outcome]:
        match intent:
            case s.Help():
                return self._help(), Outcome.SUCCESS
            case s.Greet():
                return "Yes? What would you like me to do?", Outcome.SUCCESS
            case s.GoToSleep():
                self._on_go_to_sleep()
                return f"Going to sleep. Say “{self._wake_phrase}” when you need me.", Outcome.SUCCESS
            case s.AskQuestion(question=question):
                if self._llm is None:
                    return QUESTION_REPLY, Outcome.REJECTED
                return self._ask_ai(question)
        if self._executor is None or not self._executor.handles(intent):
            return (f"I understood: {self.describe(intent)}. I can't control the computer yet.",
                    Outcome.REJECTED)
        return _from_decision(self._executor.request(intent))

    def _ask_ai(self, text: str) -> tuple[str, Outcome]:
        """The offline parser couldn't help: let the AI pick an allowed action or answer."""
        if not self._llm.configured:
            return NO_AI_KEY_REPLY, Outcome.REJECTED
        self._on_thinking()
        try:
            result, provider = self._llm.interpret(text)
        except AllProvidersFailed as exc:
            log.warning("No AI reply: %s", exc)
            if exc.nothing_configured:
                return NO_AI_KEY_REPLY, Outcome.REJECTED
            return AI_UNREACHABLE_REPLY, Outcome.FAILED
        if isinstance(result, Answer):
            return result.text, Outcome.SUCCESS
        # A validated, allowlisted action - handled exactly like a spoken command,
        # so the safety executor still decides (confirmation, authorization).
        log.info("AI (%s) chose %s", provider, result.intent.model_dump_json())
        return self._handle(result.intent)

    def _confirm(self) -> tuple[str, Outcome]:
        decision = self._executor.confirm() if self._executor else None
        if decision is None:
            return NOTHING_TO_CONFIRM, Outcome.REJECTED
        return _from_decision(decision)

    def _deny(self) -> tuple[str, Outcome]:
        dropped = self._executor.drop_pending("the user said no") if self._executor else None
        if dropped is None:
            return NOTHING_TO_CONFIRM, Outcome.REJECTED
        return f"Okay, I won't {self.describe(dropped)}.", Outcome.SUCCESS

    def _cancel(self) -> tuple[str, Outcome]:
        if self._executor is not None:
            dropped = self._executor.drop_pending("the user cancelled")
            if dropped is not None:
                return f"Okay, I won't {self.describe(dropped)}.", Outcome.SUCCESS
        message = self._cancel_scheduled()
        if message:
            return message, Outcome.SUCCESS
        return NOTHING_TO_CANCEL, Outcome.SUCCESS

    def _drop_pending(self, reason: str) -> str | None:
        dropped = self._executor.drop_pending(reason) if self._executor else None
        return f"I've cancelled the request to {self.describe(dropped)}." if dropped else None

    def _after_dropping_pending(self, reply: str, outcome: Outcome) -> tuple[str, Outcome]:
        # Something unrelated or unclear was said while a "yes" was expected:
        # never treat it as consent, and say so.
        note = self._drop_pending("an unrecognised reply was given")
        return (f"{note} {reply}" if note else reply), outcome

    def _help(self) -> str:
        examples = [self.name_for(app_id) for app_id in list(self._catalog.apps)[:2]]
        example_app = " or ".join(examples) or "an app"
        text = (
            f"You can say things like: open {example_app}, set the volume to 50 percent, "
            "turn the brightness down, take a screenshot, or lock the computer. "
            "Say repeat to hear my last answer, or go to sleep when you're done."
        )
        if self._executor is None:
            text += " For now I understand those commands but can't carry out the computer ones yet."
        else:
            text += " Before sleep, restart or shut down I'll always ask you to confirm."
        if self._llm is not None and self._llm.configured:
            text += " You can also ask me general questions."
        return text


def _from_decision(decision) -> tuple[str, Outcome]:
    if isinstance(decision, NeedsConfirmation):
        return decision.prompt, Outcome.PENDING
    if isinstance(decision, Refused):
        return decision.reason, Outcome.REJECTED
    result = decision.result
    message = result.message[:1].upper() + result.message[1:]  # "google chrome is open."
    return message, (Outcome.SUCCESS if result.success else Outcome.FAILED)


def _summary(result) -> str:
    if isinstance(result, Understood):
        return result.intent.model_dump_json()
    if isinstance(result, Invalid):
        return f"invalid ({result.reason})"
    return "not understood"
