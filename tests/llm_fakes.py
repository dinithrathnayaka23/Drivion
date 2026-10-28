"""A fake HTTP transport for the AI providers: scripted replies, no network."""

from __future__ import annotations

import json

from pydantic import SecretStr

from drivion.llm.providers import PROVIDER_ENDPOINTS, ChatProvider, ProviderUnavailable


def chat_body(content: str) -> bytes:
    return json.dumps({"choices": [{"message": {"role": "assistant", "content": content}}]}).encode()


def answer(text: str) -> tuple[int, bytes]:
    return 200, chat_body(json.dumps({"answer": text}))


def action(**intent) -> tuple[int, bytes]:
    return 200, chat_body(json.dumps({"action": intent}))


class FakeTransport:
    """Replies per provider host, in order. A reply may be (status, body) or an exception."""

    def __init__(self, script: dict[str, list]):
        self.script = {name: list(replies) for name, replies in script.items()}
        self.requests: list[dict] = []

    def __call__(self, url, headers, body, timeout):
        provider = next(name for name, (base, _) in PROVIDER_ENDPOINTS.items() if url.startswith(base))
        self.requests.append({"provider": provider, "url": url, "headers": headers,
                              "body": json.loads(body), "timeout": timeout})
        replies = self.script.get(provider, [])
        if not replies:
            raise ProviderUnavailable("no scripted reply")
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def calls(self, provider=None):
        return [r for r in self.requests if provider is None or r["provider"] == provider]


def provider(name: str, transport, key: str | None = "test-key-123", model: str = "test-model"):
    base, headers = PROVIDER_ENDPOINTS[name]
    return ChatProvider(name, model, SecretStr(key) if key else None, base, dict(headers), transport)
