"""Turns a request the offline parser couldn't handle into an action or an answer.

The model is told to reply with JSON that is EITHER

    {"action": {"kind": "SET_VOLUME", "percent": 40}}     - pick one allowed action
    {"answer": "Paris is the capital of France."}         - or just answer

and the reply is then checked in code - the prompt is a request, the checks
are the rule:

1. it must be valid JSON with exactly one of those keys;
2. an action must be one of ``LLM_ACTIONS`` (no yes/no/cancel/repeat: the AI
   can never approve or dismiss a confirmation on your behalf);
3. it must validate through ``INTENT_ADAPTER`` (types and ranges);
4. any app, website or folder must be in your allowlist.

A reply that fails any check is unusable, and the next provider is tried.
Even a valid action is still only a *request*: it goes through the
``SafeExecutor`` like any spoken command (confirmation, authorization).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError

from drivion.intents import schemas as s
from drivion.intents.catalog import Catalog
from drivion.llm.fallback import FallbackChat

# What the AI may choose. Conversation controls (Confirm, Deny, Cancel, Repeat,
# Greet) and AskQuestion are deliberately excluded.
LLM_ACTIONS: tuple[type, ...] = (
    s.SetVolume, s.ChangeVolume, s.Mute, s.Unmute, s.SetBrightness, s.ChangeBrightness,
    s.OpenApp, s.OpenWebsite, s.OpenFolder, s.MinimizeApp, s.RestoreApp,
    s.LockComputer, s.TakeScreenshot, s.SleepComputer, s.RestartComputer, s.ShutdownComputer,
    s.Help, s.GoToSleep,
)
_ALLOWED_KINDS = {m.model_fields["kind"].default for m in LLM_ACTIONS}
MAX_ANSWER_CHARS = 600


@dataclass(frozen=True)
class Action:
    intent: s._Intent


@dataclass(frozen=True)
class Answer:
    text: str


def _describe_fields(model: type) -> str:
    schema = model.model_json_schema()
    parts = []
    for name, prop in schema.get("properties", {}).items():
        if name == "kind":
            continue
        if "enum" in prop:
            kind = " | ".join(f'"{v}"' for v in prop["enum"])
        elif prop.get("type") == "integer":
            kind = f"integer {prop.get('minimum', '')}..{prop.get('maximum', '')}"
        else:
            kind = "string"
        optional = "" if name in schema.get("required", []) else " (optional)"
        parts.append(f"{name}: {kind}{optional}")
    return ", ".join(parts)


def system_prompt(catalog: Catalog) -> str:
    actions = "\n".join(
        f'- {m.model_fields["kind"].default}' + (f" ({_describe_fields(m)})" if _describe_fields(m) else "")
        for m in LLM_ACTIONS
    )
    return f"""You are Drivion, a voice assistant on the user's Windows PC. Your reply is spoken aloud.

Reply with ONE JSON object and nothing else, in exactly one of these two forms:
{{"action": {{"kind": "<KIND>", ...parameters}}}}  - when the user clearly asks you to do one of the actions below
{{"answer": "<text>"}}                              - for everything else (questions, chat, requests you can't do)

Allowed actions:
{actions}

Allowed values (use these ids exactly; never invent others):
- app: {", ".join(catalog.apps) or "(none)"}
- site: {", ".join(catalog.websites) or "(none)"}
- folder: {", ".join(catalog.folders) or "(none)"}

Rules:
- Only use an action if it clearly matches the request; if unsure, answer instead.
- You cannot run programs, commands, scripts or anything not listed. If asked, say so in an answer.
- SLEEP_COMPUTER, RESTART_COMPUTER and SHUTDOWN_COMPUTER are only for explicit requests; the user will be asked to confirm.
- GO_TO_SLEEP means the assistant itself goes to standby, not the computer.
- Answers: at most two short sentences, plain text, no markdown, lists or emoji.
- If you don't know something (for example live news, weather or the current time), say you can't check that."""


def parse_reply(text: str, catalog: Catalog) -> Action | Answer:
    """Validate a model reply. Raises ``ValueError`` if it's unusable."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("not JSON") from exc
    if not isinstance(data, dict) or len(data) != 1 or not ({"action", "answer"} & data.keys()):
        raise ValueError("needs exactly one of 'action' or 'answer'")

    if "answer" in data:
        answer = data["answer"]
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("empty answer")
        return Answer(_speakable(answer))

    action = data["action"]
    if not isinstance(action, dict) or action.get("kind") not in _ALLOWED_KINDS:
        raise ValueError(f"action {action.get('kind') if isinstance(action, dict) else action!r} not allowed")
    try:
        intent = s.INTENT_ADAPTER.validate_python(action)
    except ValidationError as exc:
        raise ValueError(f"invalid action parameters ({exc.error_count()} errors)") from exc
    _check_targets(intent, catalog)
    return Action(intent)


def _check_targets(intent, catalog: Catalog) -> None:
    allowed = {"app": catalog.apps, "site": catalog.websites, "folder": catalog.folders}
    for field, ids in allowed.items():
        value = getattr(intent, field, None)
        if value is not None and value not in ids:
            raise ValueError(f"{field} {value!r} is not in the allowlist")


def _speakable(text: str) -> str:
    text = re.sub(r"[*_`#>]+", "", text)        # markdown that would be read out
    text = " ".join(text.split())
    if len(text) > MAX_ANSWER_CHARS:
        text = text[:MAX_ANSWER_CHARS].rsplit(" ", 1)[0] + "…"
    return text


class LLMAssistant:
    def __init__(self, chat: FallbackChat, catalog: Catalog) -> None:
        self._chat = chat
        self._catalog = catalog
        self._system = system_prompt(catalog)

    @property
    def configured(self) -> bool:
        return bool(self._chat.configured)

    def interpret(self, text: str) -> tuple[Action | Answer, str]:
        """Returns (result, provider name). Raises ``AllProvidersFailed``."""
        messages = [{"role": "system", "content": self._system},
                    {"role": "user", "content": text[:1000]}]
        reply = self._chat.complete(messages, accept=lambda t: parse_reply(t, self._catalog))
        return reply.value, reply.provider
