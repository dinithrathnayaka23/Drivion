# Commands

Drivion understands commands **offline** with a rule-based parser. No internet and no AI
are involved. Every command becomes one of a fixed list of *intents*, each with checked
parameters.

> **Milestone 6 status:** help, repeat, cancel and *go to sleep* work. All other commands
> are understood and validated, but Drivion only replies "I understood: … I can't control
> the computer yet." Milestone 7 adds the safety-checked actions.

## What you can say

You don't have to use these exact words. Filler such as "please", "can you", "could you"
and "Drivion" is ignored at the start and end of a command.

| Intent | Examples | Parameters |
|---|---|---|
| `OPEN_APP` | "open Chrome", "launch VS Code", "start the calculator" | app from your allowlist |
| `OPEN_WEBSITE` | "go to YouTube", "open the GitHub website" | site from your allowlist |
| `OPEN_FOLDER` | "open my downloads folder", "show me my documents" | folder from your allowlist |
| `MINIMIZE_APP` / `RESTORE_APP` | "minimize Chrome", "bring back VS Code" | app from your allowlist |
| `SET_VOLUME` | "set the volume to 40%", "volume 75", "volume to max" | 0–100 |
| `CHANGE_VOLUME` | "turn the volume up", "turn it up by 20", "louder", "quieter" | up/down, 1–100 (default 10) |
| `MUTE` / `UNMUTE` | "mute", "turn off the sound", "turn the sound back on" | – |
| `SET_BRIGHTNESS` | "set the brightness to 70 percent", "brightness to half" | 0–100 |
| `CHANGE_BRIGHTNESS` | "brighter", "dim the screen", "increase brightness by 30" | up/down, 1–100 (default 10) |
| `LOCK_COMPUTER` | "lock the computer", "lock the screen", "lock" | – |
| `TAKE_SCREENSHOT` | "take a screenshot", "screenshot" | – |
| `SLEEP_COMPUTER` | "put my computer to sleep", "put the PC into sleep mode" | – (will need confirmation) |
| `RESTART_COMPUTER` | "restart the computer", "reboot" | – (will need confirmation) |
| `SHUTDOWN_COMPUTER` | "shut down the computer", "turn off the laptop" | – (will need confirmation) |
| `ASK_QUESTION` | "what time is it?", "tell me a joke" | the question (AI arrives in Milestone 8) |
| `GO_TO_SLEEP` | "Drivion, go to sleep", "go to standby", "that's all", "goodbye" | – |
| `HELP` | "help", "what can you do?" | – |
| `REPEAT` | "repeat that", "say that again", "what did you say?" | – |
| `CANCEL` | "cancel", "never mind", "stop", **"don't …"** | – |
| `CONFIRM` / `DENY` | "yes", "okay", "go ahead" / "no", "nope" | – (used for confirmations in Milestone 7) |
| `GREET` | "Hey Drivion", "hello" | – |

### Standby vs Windows sleep

These are different intents and are never confused:

- **"Drivion, go to sleep"**, "go to sleep" or "sleep" → `GO_TO_SLEEP`: the dashboard
  closes and Drivion returns to standby. Windows keeps running.
- **"Put my computer to sleep"**, or any phrase that names the computer → `SLEEP_COMPUTER`:
  Windows sleep, which will always need confirmation.

## How it decides (and why it's safe)

1. **Normalise** the transcript: lowercase, "45%" or "forty-five percent" → `45 percent`,
   contractions expanded, and polite and addressing words stripped from the ends.
   Whisper spells the made-up name "Drivion" differently every time ("Drivian",
   "Dravian", "Dr. Vian"), so any 5–9 letter word (or pair of words) that is at least 70%
   similar to "drivion" counts as the name. Similar real words like "driving" are kept.
2. **Match whole sentences only.** Each rule must match the *entire* normalised sentence.
   "Open Chrome and delete my files" matches nothing, and "don't open Chrome" is a
   `CANCEL`, never `OPEN_APP`.
3. **Validate** with pydantic. "Set the volume to 150%" is understood but rejected: *"The
   volume must be between 0 and 100 percent."*
4. **Only allowlisted targets.** "Open Spotify" (not in your list) or "go to example.com"
   is refused. Drivion never opens an arbitrary program, address or path. App names are
   **not** fuzzy-matched: guessing which app you meant is how the wrong thing gets opened.
5. **Questions**, i.e. sentences that start with what, who, how, can, tell me and so on,
   become `ASK_QUESTION`. Anything else gets *"Sorry, I don't know how to do that yet."*

Every intent is defined in `src/drivion/intents/schemas.py` and validated through one
`INTENT_ADAPTER`. In Milestone 8, the AI's answers will be validated by the same adapter,
so the AI can only choose one of these intents, with valid parameters.

## Your allowlist

The defaults are below. Override any of the three tables in `config/settings.toml` (see
`config/settings.example.toml`). A table you set replaces that table's defaults.

| Kind | Id | Spoken names |
|---|---|---|
| App | `chrome` | chrome, google chrome, browser, web browser |
| App | `vscode` | vscode, vs code, visual studio code, code editor |
| App | `explorer` | explorer, file explorer, windows explorer, files |
| App | `notepad` | notepad |
| App | `calculator` | calculator, calc |
| Website | `youtube`, `google`, `github`, `gmail` | the id itself |
| Folder | `downloads`, `documents`, `desktop`, `pictures` | the id itself |

Rules: websites must be `https://`; ids are lowercase letters, digits or `_` (an
underscore is spoken as a space); and a spoken name can only mean one thing. Breaking any
of these stops Drivion at startup with a clear error.

## Trying it without a microphone

Run `drivion --simulate`. Once the dashboard is open, *Simulate → Voice command* sends
sample phrases through the real parser and responder: "Open Chrome.", "Set the volume to
150%.", "Put my computer to sleep.", "Help.", "Repeat that." and others.

## Limits

- English only, and these phrasings only. Anything else becomes a question or "I don't
  know how to do that". Milestone 8's AI can handle free-form requests.
- Misheard names aren't corrected. In testing Whisper heard a synthetic voice's "Chrome" as
  "Crow". If a name is often misheard for your voice, add the misheard word as an alias.
- One command per sentence. "Open Chrome and YouTube" isn't split.
