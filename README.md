# Drivion

Drivion is a personal, voice-controlled AI desktop assistant for Windows. It wakes on
"Wake up, Drivion", verifies your face, and then accepts spoken commands.

> **Status: Milestone 5 (speech).** Drivion runs as a tray app with an animated
> dashboard. In standby it listens for a wake word, and while active it transcribes
> spoken commands and answers aloud, all offline. It doesn't act on commands yet
> (Milestone 6), and face verification, AI and system control aren't built yet; a
> developer menu (`--simulate`) fakes those events. See
> [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/WAKE_WORD.md](docs/WAKE_WORD.md)
> and [docs/SPEECH.md](docs/SPEECH.md).

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
- **Open Drivion** (tray click or menu) also starts face verification. Real verification
  arrives in Milestone 9; until then nothing answers, so after
  `face.verification_timeout_s` seconds Drivion **fails closed** and returns to standby.
- With `--simulate`, use *Simulate → Wake word detected*, then *Face verified*, to reach
  **ACTIVE** and open the dashboard.
- **Voice commands:** when the dashboard opens, Drivion says *"I'm listening."* Speak
  a command and it appears in the conversation and history, and Drivion repeats it
  aloud. It doesn't act on commands until Milestone 6. After 20 seconds of silence it
  returns to standby. See [docs/SPEECH.md](docs/SPEECH.md).
- *Simulate → Voice command* adds scripted fake commands instead (nothing is executed).
  *Toggle camera indicator* previews the privacy indicator.
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
| Face verification | Only for the first model download |
| General questions (cloud LLM) | Yes |

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
