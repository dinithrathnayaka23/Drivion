"""Chat providers: Gemini, Groq and OpenRouter, all via one OpenAI-compatible client.

All three expose the same ``POST {base}/chat/completions`` API with a
Bearer key, so a single small client (stdlib ``urllib``, no SDKs) serves
them. Errors are classified so the fallback chain knows what to do:

* ``AuthError``       401/403 - bad or missing key: skip this provider for a while
* ``RateLimited``     429     - quota exhausted: skip it briefly
* ``ProviderUnavailable``     - network down, timeout, 5xx: try the next one now
* ``BadResponse``             - 4xx or a reply we can't use: try the next one

API keys are only read at the moment a request is sent and are never logged.
``DRIVION_LLM_OFFLINE`` (always set by the test suite) blocks every real
request, so tests can never reach the internet or spend quota.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import SecretStr

log = logging.getLogger(__name__)

OFFLINE_ENV = "DRIVION_LLM_OFFLINE"

# provider -> (OpenAI-compatible base URL, extra headers)
PROVIDER_ENDPOINTS: dict[str, tuple[str, dict[str, str]]] = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", {}),
    "groq": ("https://api.groq.com/openai/v1", {}),
    # OpenRouter asks apps to identify themselves (optional, no personal data).
    "openrouter": ("https://openrouter.ai/api/v1", {"X-Title": "Drivion"}),
}


class LLMError(Exception):
    pass


class AuthError(LLMError):
    pass


class RateLimited(LLMError):
    pass


class ProviderUnavailable(LLMError):
    pass


class BadResponse(LLMError):
    pass


# (url, headers, body bytes, timeout) -> (HTTP status, response bytes)
Transport = Callable[[str, dict[str, str], bytes, float], tuple[int, bytes]]


def urllib_transport(url: str, headers: dict[str, str], body: bytes, timeout: float) -> tuple[int, bytes]:
    if os.environ.get(OFFLINE_ENV):
        raise ProviderUnavailable(f"network access disabled ({OFFLINE_ENV} is set)")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
        raise ProviderUnavailable(f"network error: {getattr(exc, 'reason', exc)}") from exc


@dataclass
class ChatProvider:
    name: str
    model: str
    api_key: SecretStr | None
    base_url: str
    extra_headers: dict[str, str] = field(default_factory=dict)
    transport: Transport = urllib_transport

    @property
    def configured(self) -> bool:
        return self.api_key is not None

    def complete(self, messages: list[dict[str, str]], max_tokens: int, timeout: float) -> str:
        if self.api_key is None:
            raise AuthError("no API key configured")
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key.get_secret_value()}",
            **self.extra_headers,
        }
        status, raw = self.transport(f"{self.base_url}/chat/completions", headers, body, timeout)
        if status in (401, 403):
            raise AuthError(f"key rejected (HTTP {status})")
        if status == 429:
            raise RateLimited("rate limit or quota reached")
        if status >= 500:
            raise ProviderUnavailable(f"server error (HTTP {status})")
        if status != 200:
            raise BadResponse(f"request rejected (HTTP {status}): {_error_text(raw)}")
        return _content(raw)


def _error_text(raw: bytes) -> str:
    try:
        error = json.loads(raw)
        if isinstance(error, list) and error:
            error = error[0]
        return str(error.get("error", {}).get("message", ""))[:200]
    except (ValueError, AttributeError):
        return raw[:200].decode("utf-8", "replace")


def _content(raw: bytes) -> str:
    try:
        message = json.loads(raw)["choices"][0]["message"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise BadResponse("reply wasn't in the expected format") from exc
    content = message.get("content")
    if isinstance(content, list):  # some providers return content parts
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not isinstance(content, str) or not content.strip():
        raise BadResponse("empty reply")
    return content


def build_providers(settings, secrets, transport: Transport = urllib_transport) -> list[ChatProvider]:
    """Providers in fallback order. ``settings`` is the [llm] config section."""
    providers = []
    for name in settings.providers:
        base_url, headers = PROVIDER_ENDPOINTS[name]
        providers.append(ChatProvider(name, settings.model_for(name), secrets.key_for(name),
                                      base_url, dict(headers), transport))
    return providers
