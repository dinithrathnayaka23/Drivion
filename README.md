# Drivion

Drivion is a personal, voice-controlled AI desktop assistant for Windows. It wakes on
"Wake up, Drivion", verifies your face, and then accepts spoken commands.

> **Status: Milestone 4 (wake word).** Drivion runs as a tray app with an animated
> dashboard, and in standby it listens for a wake word with openWakeWord, offline.
> Face verification, speech commands, AI and system control are not built yet; a
> developer menu (`--simulate`) fakes those events. See
> [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the plan and
> [docs/WAKE_WORD.md](docs/WAKE_WORD.md) for wake-word setup.

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

Then download the wake-word models once (about 3.6 MB; each file is checked against a
pinned SHA-256 hash):

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
- While the dashboard is open, *Simulate → Voice command* adds fake commands to the
  conversation and history (nothing is executed). *Toggle microphone/camera indicator*
  previews the privacy indicators.
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

## Offline vs online

| Feature | Needs internet? |
|---|---|
| Config, logging, UI | No |
| Wake word (openWakeWord) | Only for the one-time `--download-models` |
| Speech-to-text (faster-whisper) | Only for the first model download |
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
- **"Drivion is already running":** a copy is running in the tray. Use its *Exit Drivion*
  menu item, or end `python.exe` in Task Manager.

## License

MIT, see [LICENSE](LICENSE).
