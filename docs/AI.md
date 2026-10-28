# AI providers (Gemini, Groq, OpenRouter)

Drivion understands simple commands **offline**. The cloud AI is used only for what the
offline parser can't handle:

- **questions**: "who wrote Hamlet?"
- **free-form requests** that don't match a known phrasing: "I can barely hear anything,
  crank it up"

Commands like "set the volume to 40 percent" or "open Chrome" never leave your computer.

## Setup

1. Get at least one API key. More keys give more resilience, because Drivion falls back
   between them:
   - Gemini: https://aistudio.google.com/apikey
   - Groq: https://console.groq.com/keys
   - OpenRouter: https://openrouter.ai/keys
2. Copy `.env.example` to `.env` (already done in this repo) and replace the
   placeholders:
   ```
   DRIVION_GEMINI_API_KEY=AIza...
   DRIVION_GROQ_API_KEY=gsk_...
   DRIVION_OPENROUTER_API_KEY=sk-or-...
   ```
3. Run `drivion --check-config` to see which keys Drivion detects. It never prints the
   keys themselves.

`.env` is git-ignored. Keys are never put in `settings.toml`, never written in the code,
and never logged; the log redaction filter masks them even if a provider echoes one back.
A value that is empty or looks like a placeholder (`your-…`, `<…>`, `changeme`) counts as
"not configured", and Drivion skips that provider without sending anything.

## Model fallback

```
your request ─► Gemini ──fails──► Groq ──fails──► OpenRouter ──fails──► "I couldn't reach any AI service"
```

| What went wrong | What Drivion does |
|---|---|
| No key for a provider | Skips it |
| Key rejected (401/403) | Tries the next provider and pauses that one for 10 minutes. Check its key. |
| Rate limit or quota (429) | Tries the next provider and pauses that one for `rate_limit_cooldown_s` (60 s) |
| Offline, timeout or server error | Tries the next provider straight away |
| A reply that breaks the rules (see below) | Tries the next provider |
| No keys at all | *"No AI service is set up. Add an API key to the .env file."* |

Settings, in `[llm]` of `config/settings.toml`:

```toml
[llm]
enabled = true
providers = ["gemini", "groq", "openrouter"]   # order = fallback order
gemini_model = "gemini-3.5-flash-lite"
groq_model = "llama-3.3-70b-versatile"
openrouter_model = "google/gemma-4-31b-it:free"
request_timeout_s = 10.0
max_answer_tokens = 300
rate_limit_cooldown_s = 60.0
```

Model names were checked against each provider's model list in October 2026.
OpenRouter's free models in particular change often, so if one stops working, pick
another from https://openrouter.ai/models (filter by "free").

## How the AI is kept on a leash

All three providers use the same OpenAI-compatible API (`/chat/completions`), so one small
client in `llm/providers.py` handles them all, using only Python's standard library.

The AI must reply with JSON in exactly one of two forms:

```json
{"action": {"kind": "SET_VOLUME", "percent": 80}}
{"answer": "Shakespeare wrote Hamlet."}
```

The prompt asks for this, and **code enforces it** (`llm/assistant.py`):

1. The reply must be valid JSON with exactly one of those two keys. Anything else, such
   as `{"command": "shutdown /s"}`, is rejected.
2. The action must be in `LLM_ACTIONS`: the system actions plus help and go to sleep.
   **Yes, no, cancel and repeat are excluded**, so the AI can never approve or dismiss a
   confirmation for you.
3. It must validate through the same `INTENT_ADAPTER` as spoken commands, so types and
   ranges are checked and unknown fields are rejected.
4. Any app, website or folder must be in your allowlist.
5. Even then it is only a *request*. It goes through the `SafeExecutor`, so Drivion must
   be unlocked, and sleep, restart and shut down still wait for **your** spoken "yes".

A reply that fails a check is treated like a provider failure, and the next provider is
asked.

## Privacy

- Only the single sentence the offline parser couldn't handle is sent, together with the
  instructions and your allowlist ids (for example `chrome, youtube, downloads`).
- No audio, no history and no files are sent.
- Turn it off with `enabled = false` under `[llm]`.
- Each provider's own terms decide how it stores requests. Free tiers may use requests to
  improve their models, so check before sending anything sensitive.

## Testing

The tests never touch the network. A fake transport (`tests/llm_fakes.py`) scripts every
reply, and `DRIVION_LLM_OFFLINE=1`, which the test suite always sets, makes the real
transport refuse to send anything.

## Limits

- Needs internet and at least one valid key.
- No conversation memory: each request is answered on its own.
- Live information (news, weather, the current time) isn't available to the model. It's
  instructed to say so rather than guess.
- Free tiers have strict rate limits; the fallback chain helps, but can't remove them.
