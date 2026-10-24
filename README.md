# Drivion

Drivion is a personal, voice-controlled AI desktop assistant for Windows. It wakes on
"Wake up, Drivion", verifies your face, and then accepts spoken commands.

> **Status: Milestone 1 (scaffolding).** Only configuration, logging and a placeholder
> window exist so far. There is no microphone, camera, AI or system control yet.
> See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full plan.

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
drivion                     # open the window
python -m drivion           # same thing
```

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

## License

MIT, see [LICENSE](LICENSE).
