"""Model fallback: try each AI provider in order until one gives a usable reply.

    Gemini ──fails──► Groq ──fails──► OpenRouter ──fails──► AllProvidersFailed

* Providers without a key are skipped (they're "not configured", not broken).
* A rejected key puts that provider on a long cooldown (it won't fix itself);
  a rate limit puts it on a short one. Cooled-down providers are skipped.
* Network errors, timeouts and server errors move on immediately.
* ``accept`` lets the caller validate a reply. If it raises ``ValueError``
  the reply counts as unusable and the next provider gets a chance - a model
  that answers with invalid JSON is as useless as one that's offline.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from drivion.llm.providers import AuthError, ChatProvider, LLMError, RateLimited

log = logging.getLogger(__name__)

T = TypeVar("T")
AUTH_COOLDOWN_S = 600.0


class AllProvidersFailed(Exception):
    def __init__(self, reasons: dict[str, str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(f"{name}: {why}" for name, why in reasons.items()) or
                         "no AI provider is configured")

    @property
    def nothing_configured(self) -> bool:
        return not self.reasons


@dataclass(frozen=True)
class Reply:
    value: object
    provider: str
    seconds: float


class FallbackChat:
    def __init__(self, providers: list[ChatProvider], timeout_s: float, max_tokens: int,
                 rate_limit_cooldown_s: float = 60.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.providers = providers
        self._timeout = timeout_s
        self._max_tokens = max_tokens
        self._rate_limit_cooldown = rate_limit_cooldown_s
        self._clock = clock
        self._cooldown_until: dict[str, float] = {}
        self._lock = threading.Lock()

    @property
    def configured(self) -> list[str]:
        return [p.name for p in self.providers if p.configured]

    def complete(self, messages: list[dict[str, str]], accept: Callable[[str], T]) -> Reply:
        reasons: dict[str, str] = {}
        for provider in self.providers:
            if not provider.configured:
                continue
            wait = self._cooling(provider.name)
            if wait:
                reasons[provider.name] = f"paused for {wait:.0f}s after an earlier error"
                continue
            started = self._clock()
            try:
                text = provider.complete(messages, self._max_tokens, self._timeout)
                value = accept(text)
            except ValueError as exc:  # unusable reply -> next provider
                reasons[provider.name] = f"unusable reply ({exc})"
            except AuthError as exc:
                reasons[provider.name] = f"{exc} - check its key in .env"
                self._cool_down(provider.name, AUTH_COOLDOWN_S)
            except RateLimited as exc:
                reasons[provider.name] = str(exc)
                self._cool_down(provider.name, self._rate_limit_cooldown)
            except LLMError as exc:  # unavailable, timeout, bad request
                reasons[provider.name] = str(exc)
            else:
                seconds = self._clock() - started
                log.info("AI reply from %s (%s) in %.2fs", provider.name, provider.model, seconds)
                return Reply(value, provider.name, seconds)
            log.warning("AI provider %s failed: %s", provider.name, reasons[provider.name])
        raise AllProvidersFailed(reasons)

    def _cooling(self, name: str) -> float:
        with self._lock:
            return max(0.0, self._cooldown_until.get(name, 0.0) - self._clock())

    def _cool_down(self, name: str, seconds: float) -> None:
        if seconds > 0:
            with self._lock:
                self._cooldown_until[name] = self._clock() + seconds
