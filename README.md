# Drivion

Drivion is a personal, voice-controlled AI desktop assistant for Windows. It wakes on
"Wake up, Drivion", verifies your face, and then accepts spoken commands.

> **Status: Milestone 10 (liveness).** Drivion runs as a tray app with an
> animated dashboard. In standby it listens for a wake word, then **checks your face**
> (local, encrypted templates) and asks for **random head turns** before opening the
> dashboard. While active it understands
> spoken commands offline and carries them out through a safety layer (sleep, restart and
> shut down only after you confirm). Questions go to a cloud AI, with fallback between
> Gemini, Groq and OpenRouter. See
> [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/FACE.md](docs/FACE.md),
> [docs/COMMANDS.md](docs/COMMANDS.md), [docs/ACTIONS.md](docs/ACTIONS.md) and
> [docs/AI.md](docs/AI.md).

## Requirements

- Windows 10/11
- Python **3.11** (check with `py -0p`; install it from python.org if `3.11` isn't listed)

## Setup (PowerShell)

```powershell
cd "C:\Users\MSI GF63\Desktop\Pet projects\Drivion"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1          # your prompt now starts with (.venv)
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

If `Activate.ps1` is blocked by the execution policy, run this once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

`-e` installs Drivion in *editable* mode, so your code changes take effect without
reinstalling.

Then download the models once: the wake word (about 3.6 MB, each file checked against a
pinned SHA-256 hash) and speech recognition (`base.en`, about 150 MB, from a pinned
revision):

```powershell
drivion --download-models
```

Then enroll your face. The window asks for your consent first, and stores encrypted
templates, not photos. See [docs/FACE.md](docs/FACE.md).

```powershell
drivion --enroll-face
drivion --test-face        # optional: live match score vs the threshold
```

## Configuration

| File | Contains | In Git? |
|---|---|---|
| `config/settings.example.toml` | Documented defaults | yes |
| `config/settings.toml` | Your settings (copy of the example) | **no** |
| `.env.example` | Secret placeholders | yes |
| `.env` | Your real API keys | **no** |

```powershell
Copy-Item config\settings.example.toml config\settings.toml
Copy-Item .env.example .env
```

Every setting is optional. Invalid values (for example `sensitivity = 1.5`) or unknown
keys stop Drivion at startup with a message that names the bad setting.

**AI keys (optional).** In `.env`, replace the placeholders for any of
`DRIVION_GEMINI_API_KEY`, `DRIVION_GROQ_API_KEY` and `DRIVION_OPENROUTER_API_KEY`. One is
enough; with several, Drivion falls back between them. Keys only ever go in `.env`, never
in `settings.toml` or the code. Run `drivion --check-config` to see which keys are
detected; it never prints the keys. See [docs/AI.md](docs/AI.md).

Logs are written to `%LOCALAPPDATA%\Drivion\logs\drivion.log`. API keys are redacted
from log output.

## Run

```powershell
drivion --check-config      # validate config and print a summary; no window
drivion                     # start in standby (tray icon only)
drivion --simulate          # same, plus a "Simulate (developer)" tray menu
python -m drivion           # same as `drivion`
```

Drivion starts in **STANDBY**: no window opens, and a round icon appears in the system
tray (look under the `^` arrow on the taskbar). The icon colour shows the state:
blue = standby, amber = verifying, cyan = active, red = error.

- **Wake word:** in standby, Drivion listens for **"Hey Jarvis"** (a built-in stand-in
  until you train "Wake up, Drivion"; see [docs/WAKE_WORD.md](docs/WAKE_WORD.md)). While
  it listens, the microphone chip is on. Saying the phrase starts face verification, and
  the microphone is released straight away.
- **Face verification:** after the wake word, or **Open Drivion** in the tray, the camera
  turns on and the icon turns amber. Look at the camera. Then follow the spoken head-turn
  prompts. The dashboard then opens and the camera switches off. Anything else, such as a stranger, no face, two
  faces, poor light or no enrollment, gives *"Access denied: <reason>"* and Drivion returns
  to standby (**fail closed**).
- With `--simulate`, use *Simulate → Wake word detected*, then *Face verified*, to reach
  **ACTIVE** and open the dashboard.
- **Voice commands:** when the dashboard opens, Drivion says *"I'm listening."* Say
  things like *"open Chrome"*, *"set the volume to 40 percent"*, *"help"* or *"repeat
  that"*. **"Drivion, go to sleep"** returns it to standby, and so do 20 seconds of
  silence. Commands are carried out and checked. For **sleep, restart and shut down**
  Drivion asks *"Are you sure…?"* and acts only on a clear **yes**, and "cancel" stops a
  restart or shutdown during its 10-second delay. See
  [docs/COMMANDS.md](docs/COMMANDS.md) and [docs/ACTIONS.md](docs/ACTIONS.md).
- *Simulate → Voice command* sends harmless sample phrases through the real pipeline,
  so you can try commands without a microphone. *"Take a screenshot"* really saves one to
  `Pictures\Screenshots`. The samples never include power commands. *Toggle camera
  indicator* previews the privacy indicator.
- **Go to sleep**, or closing the window with X, returns to standby. The process keeps
  running in the tray.
- **Exit Drivion** (tray menu or window button) stops the background process. Ctrl+C in
  the terminal does the same.
- Launching Drivion a second time doesn't start a second copy. It asks the running copy to
  open and exits with code 3.

## Test

```powershell
pytest            # or: pytest -v
```

The tests run Qt offscreen and never touch your microphone, camera or power settings.
Audio tests use speech synthesized with Windows' built-in voice, and the speaker tests
run the real Windows voice at volume 0 (silent). Tests that need the downloaded models
are skipped until you run `drivion --download-models`.

## Offline vs online

| Feature | Needs internet? |
|---|---|
| Config, logging, UI | No |
| Wake word (openWakeWord) | Only for the one-time `--download-models` |
| Speech-to-text (faster-whisper) | Only for the one-time `--download-models` |
| Spoken replies (Windows voices) | No |
| Face verification (OpenCV YuNet + SFace) | Only for the one-time `--download-models` |
| Simple commands (volume, apps, lock, ...) | No: understood and carried out on your PC |
| Questions and free-form requests (Gemini, Groq, OpenRouter) | Yes, plus at least one API key in `.env` |

## Troubleshooting

- **`py -3.11` not found:** install Python 3.11 from python.org.
- **`drivion` is not recognized:** activate the venv first (`.\.venv\Scripts\Activate.ps1`).
- **"Drivion configuration error: ...":** fix the setting named in the message, or delete
  `config/settings.toml` to go back to the defaults.
- **Nothing seems to happen when I run `drivion`:** that's standby. Look for the tray
  icon under the taskbar's `^` arrow.
- **"Wake word unavailable":** run `drivion --download-models`. If it still appears,
  check the log for the exact reason.
- **Microphone chip shows "unavailable":** check *Settings → Privacy & security →
  Microphone* and make sure *Let desktop apps access your microphone* is on. Also check
  that no other app has exclusive use of the microphone. Then choose *Recover from
  error* in the tray.
- **The wake word never triggers:** run `drivion --list-audio-devices`, set
  `wake_word.input_device` to your microphone, or raise `wake_word.sensitivity`.
- **"No AI service is set up":** put a real key in `.env` (not the `your-...` placeholder),
  then restart Drivion. `drivion --check-config` shows which keys are detected.
- **"I couldn't reach any AI service":** check your internet connection. The log
  (`drivion.log`) says why each provider failed: a rejected key, a rate limit, a timeout,
  or an unknown model name. In the last case, update the model under `[llm]`.
- **"Access denied: face not recognised":** enroll again in good, even light
  (`drivion --enroll-face`), and check your score with `drivion --test-face`.
- **"Access denied: the camera isn't available":** close other apps that use the camera,
  and check *Settings → Privacy & security → Camera → Let desktop apps access your
  camera*.
- **"Face verification not ready":** run `drivion --download-models` and
  `drivion --enroll-face`.
- **"Voice commands unavailable":** run `drivion --download-models` (needed again if you
  change `voice.stt_model`).
- **Background noise becomes a "command", or I get cut off:** raise
  `voice.speech_threshold`, or raise `voice.end_silence_s` (see
  [docs/SPEECH.md](docs/SPEECH.md)).
- **No spoken replies:** check `voice.tts_engine = "windows"`, the system volume, and
  `drivion --list-voices`.
- **"Drivion is already running":** a copy is running in the tray. Use its *Exit Drivion*
  menu item, or end `python.exe` in Task Manager.

## License

MIT, see [LICENSE](LICENSE).
