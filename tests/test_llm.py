"""AI providers, the fallback chain and the reply validator - all with a fake transport."""

import json
import os

import pytest

from drivion.config.secrets import Secrets
from drivion.config.settings import CommandsSettings, LLMSettings
from drivion.intents import schemas as s
from drivion.intents.catalog import Catalog
from drivion.llm.assistant import LLM_ACTIONS, Action, Answer, LLMAssistant, parse_reply, system_prompt
from drivion.llm.fallback import AUTH_COOLDOWN_S, AllProvidersFailed, FallbackChat
from drivion.llm.providers import (
    OFFLINE_ENV,
    AuthError,
    BadResponse,
    ProviderUnavailable,
    RateLimited,
    build_providers,
    urllib_transport,
)
from llm_fakes import FakeTransport, action, answer, chat_body, provider

CATALOG = Catalog.from_settings(CommandsSettings())
MESSAGES = [{"role": "user", "content": "hi"}]


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


# ----- one provider ------------------------------------------------------------------------


def test_request_is_openai_compatible_and_sends_the_key_only_in_the_header():
    transport = FakeTransport({"groq": [answer("hello")]})
    text = provider("groq", transport, key="gsk-secret-1", model="llama-3.3-70b-versatile").complete(
        MESSAGES, max_tokens=300, timeout=10)
    assert json.loads(text) == {"answer": "hello"}
    request = transport.requests[0]
    assert request["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer gsk-secret-1"
    assert request["body"]["model"] == "llama-3.3-70b-versatile"
    assert request["body"]["response_format"] == {"type": "json_object"}
    assert "gsk-secret-1" not in json.dumps(request["body"])


def test_each_provider_has_its_own_endpoint():
    transport = FakeTransport({name: [answer("x")] for name in ("gemini", "groq", "openrouter")})
    for name in ("gemini", "groq", "openrouter"):
        provider(name, transport).complete(MESSAGES, 100, 5)
    urls = [r["url"] for r in transport.requests]
    assert urls == [
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "https://api.groq.com/openai/v1/chat/completions",
        "https://openrouter.ai/api/v1/chat/completions",
    ]
    assert transport.requests[2]["headers"]["X-Title"] == "Drivion"


@pytest.mark.parametrize(
    "reply, error",
    [((401, b'{"error":{"message":"bad key"}}'), AuthError), ((403, b"{}"), AuthError),
     ((429, b"{}"), RateLimited), ((503, b"{}"), ProviderUnavailable),
     ((400, b'{"error":{"message":"unknown model"}}'), BadResponse),
     ((200, b"not json"), BadResponse), ((200, b'{"choices": []}'), BadResponse),
     ((200, chat_body("")), BadResponse)],
)
def test_errors_are_classified(reply, error):
    with pytest.raises(error):
        provider("gemini", FakeTransport({"gemini": [reply]})).complete(MESSAGES, 100, 5)


def test_missing_key_is_never_sent():
    transport = FakeTransport({"gemini": [answer("x")]})
    with pytest.raises(AuthError):
        provider("gemini", transport, key=None).complete(MESSAGES, 100, 5)
    assert transport.requests == []


def test_real_transport_is_blocked_in_tests():
    assert os.environ.get(OFFLINE_ENV) == "1"  # set for every test by conftest
    with pytest.raises(ProviderUnavailable, match="disabled"):
        urllib_transport("https://api.groq.com/openai/v1/chat/completions", {}, b"{}", 5)


def test_build_providers_follows_the_configured_order_and_keys():
    settings = LLMSettings(providers=["openrouter", "gemini"])
    secrets = Secrets(_env_file=None, gemini_api_key="g-key-123456")
    providers = build_providers(settings, secrets)
    assert [p.name for p in providers] == ["openrouter", "gemini"]
    assert [p.configured for p in providers] == [False, True]
    assert providers[0].model == settings.openrouter_model


def test_duplicate_providers_are_rejected():
    with pytest.raises(ValueError):
        LLMSettings(providers=["groq", "groq"])


# ----- fallback ----------------------------------------------------------------------------


def chain(script, names=("gemini", "groq", "openrouter"), keys=None, clock=None):
    transport = FakeTransport(script)
    keys = keys or {}
    providers = [provider(n, transport, key=keys.get(n, "test-key-123")) for n in names]
    return FallbackChat(providers, 5, 100, rate_limit_cooldown_s=60, clock=clock or Clock()), transport


def accept_any(text):
    return text


def test_first_provider_answers():
    chat, transport = chain({"gemini": [answer("hi")]})
    assert chat.complete(MESSAGES, accept_any).provider == "gemini"
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    "failure",
    [(401, b"{}"), (429, b"{}"), (500, b"{}"), ProviderUnavailable("offline"), (400, b"{}")],
)
def test_falls_back_to_the_next_provider(failure):
    chat, transport = chain({"gemini": [failure], "groq": [answer("from groq")]})
    reply = chat.complete(MESSAGES, accept_any)
    assert reply.provider == "groq"
    assert [r["provider"] for r in transport.requests] == ["gemini", "groq"]


def test_providers_without_keys_are_skipped_silently():
    chat, transport = chain({"openrouter": [answer("x")]}, keys={"gemini": None, "groq": None})
    assert chat.complete(MESSAGES, accept_any).provider == "openrouter"
    assert [r["provider"] for r in transport.requests] == ["openrouter"]
    assert chat.configured == ["openrouter"]


def test_an_unusable_reply_also_falls_back():
    def strict(text):
        raise ValueError("not what I asked for")

    chat, _ = chain({"gemini": [answer("x")], "groq": [answer("y")], "openrouter": [answer("z")]})
    with pytest.raises(AllProvidersFailed) as info:
        chat.complete(MESSAGES, strict)
    assert set(info.value.reasons) == {"gemini", "groq", "openrouter"}
    assert "unusable reply" in info.value.reasons["gemini"]


def test_all_failing_reports_every_reason():
    chat, _ = chain({"gemini": [ProviderUnavailable("offline")], "groq": [(429, b"{}")],
                     "openrouter": [(401, b"{}")]})
    with pytest.raises(AllProvidersFailed) as info:
        chat.complete(MESSAGES, accept_any)
    assert not info.value.nothing_configured
    assert "check its key in .env" in info.value.reasons["openrouter"]


def test_nothing_configured():
    chat, _ = chain({}, keys={"gemini": None, "groq": None, "openrouter": None})
    with pytest.raises(AllProvidersFailed) as info:
        chat.complete(MESSAGES, accept_any)
    assert info.value.nothing_configured


def test_rate_limited_provider_is_skipped_until_its_cooldown_ends():
    clock = Clock()
    chat, transport = chain({"gemini": [(429, b"{}"), answer("back")], "groq": [answer("g1"), answer("g2")]},
                            names=("gemini", "groq"), clock=clock)
    assert chat.complete(MESSAGES, accept_any).provider == "groq"
    clock.now += 30
    assert chat.complete(MESSAGES, accept_any).provider == "groq"  # gemini still cooling down
    assert len(transport.calls("gemini")) == 1
    clock.now += 31
    assert chat.complete(MESSAGES, accept_any).provider == "gemini"


def test_rejected_key_gets_a_long_cooldown():
    clock = Clock()
    chat, transport = chain({"gemini": [(401, b"{}")], "groq": [answer("1"), answer("2")]},
                            names=("gemini", "groq"), clock=clock)
    chat.complete(MESSAGES, accept_any)
    clock.now += AUTH_COOLDOWN_S - 1
    chat.complete(MESSAGES, accept_any)
    assert len(transport.calls("gemini")) == 1


# ----- the reply validator: the AI can only pick allowed, valid, allowlisted actions -------


def reply(obj) -> str:
    return json.dumps(obj)


def test_valid_action_and_answer():
    assert parse_reply(reply({"action": {"kind": "SET_VOLUME", "percent": 30}}), CATALOG) == \
        Action(s.SetVolume(percent=30))
    assert parse_reply(reply({"action": {"kind": "OPEN_APP", "app": "chrome"}}), CATALOG) == \
        Action(s.OpenApp(app="chrome"))
    assert parse_reply(reply({"answer": "Paris."}), CATALOG) == Answer("Paris.")


def test_code_fences_and_markdown_are_cleaned():
    assert parse_reply('```json\n{"answer": "It is **bold** and `code`"}\n```', CATALOG) == \
        Answer("It is bold and code")


@pytest.mark.parametrize(
    "bad, why",
    [
        ('{"answer": "x", "action": {"kind": "MUTE"}}', "exactly one"),   # both
        ("Sure! I'll do that.", "not JSON"),
        ('{"answer": ""}', "empty"),
        ('{"command": "shutdown /s /t 0"}', "exactly one"),               # free-form command
        ('{"action": {"kind": "RUN_SHELL", "command": "del *"}}', "not allowed"),
        ('{"action": {"kind": "CONFIRM"}}', "not allowed"),               # can't say "yes" for you
        ('{"action": {"kind": "DENY"}}', "not allowed"),
        ('{"action": {"kind": "CANCEL"}}', "not allowed"),
        ('{"action": {"kind": "ASK_QUESTION", "question": "x"}}', "not allowed"),
        ('{"action": {"kind": "SET_VOLUME", "percent": 400}}', "invalid action parameters"),
        ('{"action": {"kind": "SET_VOLUME", "percent": 40, "then": "x"}}', "invalid action parameters"),
        ('{"action": {"kind": "OPEN_APP", "app": "cmd"}}', "not in the allowlist"),
        ('{"action": {"kind": "OPEN_WEBSITE", "site": "evil"}}', "not in the allowlist"),
        ('{"action": "SHUTDOWN_COMPUTER"}', "not allowed"),
    ],
)
def test_unusable_replies_are_rejected(bad, why):
    with pytest.raises(ValueError, match=why):
        parse_reply(bad, CATALOG)


def test_long_answers_are_trimmed_for_speech():
    text = parse_reply(reply({"answer": "word " * 400}), CATALOG).text
    assert len(text) <= 601 and text.endswith("…")


def test_prompt_lists_only_allowed_actions_and_allowlist_ids():
    prompt = system_prompt(CATALOG)
    for model in LLM_ACTIONS:
        assert model.model_fields["kind"].default in prompt
    for forbidden in ("CONFIRM", "DENY", "CANCEL", "REPEAT", "ASK_QUESTION"):
        assert f"- {forbidden}" not in prompt
    assert "chrome" in prompt and "youtube" in prompt and "downloads" in prompt
    assert "percent: integer 0..100" in prompt


def test_assistant_falls_back_past_a_model_that_breaks_the_rules():
    transport = FakeTransport({
        "gemini": [(200, chat_body('{"action": {"kind": "RUN_SHELL"}}'))],
        "groq": [action(kind="MUTE")],
    })
    chat = FallbackChat([provider("gemini", transport), provider("groq", transport)], 5, 100)
    result, used = LLMAssistant(chat, CATALOG).interpret("make it silent")
    assert (result, used) == (Action(s.Mute()), "groq")
    system, user = transport.requests[0]["body"]["messages"]
    assert system["role"] == "system" and user == {"role": "user", "content": "make it silent"}
