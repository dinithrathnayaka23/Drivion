# Drivion

Drivion is a personal, voice-controlled AI desktop assistant for Windows. It wakes on
"Wake up, Drivion", verifies your face, and then accepts spoken commands.

> **Status: Milestone 2 (core lifecycle).** The app has a state machine, a system tray
> icon, a single-instance lock, and infrastructure for background services. There is no
> microphone, camera, AI or system control yet; a developer menu (`--simulate`) fakes
> those events. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full plan.

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

- **Open Drivion** (tray click or menu) starts face verification. Real verification
  arrives in Milestone 9; until then nothing answers, so after
  `face.verification_timeout_s` seconds Drivion **fails closed** and returns to standby.
- With `--simulate`, use *Simulate → Wake word detected*, then *Face verified*, to reach
  **ACTIVE** and open the dashboard.
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
| Wake word (Porcupine) | AccessKey validation (to be confirmed in M4) |
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
- **"Drivion is already running":** a copy is running in the tray. Use its *Exit Drivion*
  menu item, or end `python.exe` in Task Manager.

## License

MIT, see [LICENSE](LICENSE).
