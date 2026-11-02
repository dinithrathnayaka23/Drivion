# Drivion

Drivion is a personal, voice-controlled AI desktop assistant for Windows. It wakes on
"Wake up, Drivion", verifies your face, and then accepts spoken commands.

> **Status: all 12 milestones are built.** Drivion runs as a tray app with an
> animated dashboard. In standby it listens for a wake word, then **checks your face**
> (local, encrypted templates) and asks for **random head turns** before opening the
> dashboard. While active it understands
> spoken commands offline and carries them out through a safety layer (sleep, restart and
> shut down only after you confirm). Questions go to a cloud AI, with fallback between
> Gemini, Groq and OpenRouter. See
> [docs/RECOVERY.md](docs/RECOVERY.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md),
> [docs/FACE.md](docs/FACE.md),
> [docs/COMMANDS.md](docs/COMMANDS.md), [docs/ACTIONS.md](docs/ACTIONS.md) and
> [docs/AI.md](docs/AI.md).

## Install

There are two ways to run Drivion. Use the packaged build if you just want to use it, and
the source setup if you want to change the code. See [Build it](#build-the-windows-package)
to produce `dist\Drivion`, which is what you copy to a computer.

### Packaged build

You need Windows 10/11 and about 1 GB of disk space. You don't need Python.

1. Copy the `Drivion` folder somewhere permanent, such as `C:\Apps\Drivion`. Keep every
   file together: the programs need the `_internal` folder beside them.
2. Open PowerShell in that folder, then download the models and enroll your face:
   ```powershell
   .\drivion.exe --download-models
   .\drivion.exe --enroll-face
   .\drivion.exe --self-test        # proves every engine works on this computer
   ```
3. Double-click **DrivionApp.exe**. A tray icon appears, and no window opens until you
   wake Drivion.

The folder has two programs that share everything in `_internal`:

| Program | Use it for |
|---|---|
| `DrivionApp.exe` | Everyday use, with no console window. Start at login uses this one |
| `drivion.exe` | Every command in this guide, such as `--doctor`, because it can print to PowerShell |

In a packaged build, type `.\drivion.exe` wherever this guide says `drivion`, unless you
add the folder to your PATH.

The build isn't code-signed, so Windows SmartScreen may warn you the first time. Choose
*More info → Run anyway* only for a build you made or trust.

### From source

Requirements:

- Windows 10/11
- Python **3.11** (check with `py -0p`; install it from python.org if `3.11` isn't listed)

In PowerShell:

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

### Model downloads

Models aren't included in the build or in Git. Download them once per computer:

```powershell
drivion --download-models
```

| Model | Size | How it's checked |
|---|---|---|
| Wake word (openWakeWord) | about 3.6 MB | Pinned SHA-256 hash for each file |
| Speech recognition (`base.en`) | about 150 MB | Pinned revision |
| Face (YuNet and SFace) | about 40 MB | Pinned SHA-256 hash for each file |

They go to `%LOCALAPPDATA%\Drivion\models` and work offline afterwards. A different
`voice.stt_model` needs this command again.

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

**In a packaged build these two files live in `%LOCALAPPDATA%\Drivion`**, not the program
folder: `%LOCALAPPDATA%\Drivion\config\settings.toml` and `%LOCALAPPDATA%\Drivion\.env`.
You usually don't need to create them, because the settings screen does that when you save.
The folder includes `settings.example.toml` and `.env.example` for reference.

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
drivion --doctor            # check everything and show how to fix any problem
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
- **Settings** (dashboard button or tray menu, only while unlocked): voice, wake word,
  privacy and AI provider. Changes apply the next time Drivion starts.
- **Go to sleep**, or closing the window with X, returns to standby. The process keeps
  running in the tray.
- **Exit Drivion** (tray menu or window button) stops the background process. Ctrl+C in
  the terminal does the same.
- Launching Drivion a second time doesn't start a second copy. It asks the running copy to
  open and exits with code 3.

## Start at login

Off by default. Turn it on with *Settings → Privacy → Start Drivion when I sign in to
Windows*, or:

```powershell
drivion --autostart on       # also: off, status
```

Drivion then starts in standby when you sign in, and **listens for the wake word from
then on**, with its tray icon showing. It doesn't unlock anything: face verification still
runs when you wake it. The setting is stored for your Windows account only and needs no
administrator rights. You can also turn it off in *Task Manager → Startup apps*.

If you move the program folder, run `drivion --autostart on` again from the new place.

## Build the Windows package

```powershell
pip install -e ".[build]"
.\packaging\build.ps1
dist\Drivion\drivion.exe --self-test
```

The build takes several minutes and makes `dist\Drivion` (about 550 MB). Your `.env`,
settings, face data and models are never included, and the script stops if it finds any
of those personal files in the output. `--self-test` runs every model and library on
silence and a blank picture, without opening the microphone or camera, so it shows
that nothing was left out of the build.

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

Run `drivion --doctor` first. [docs/RECOVERY.md](docs/RECOVERY.md) covers re-enrolling your
face and recovering from errors.

- **`py -3.11` not found:** install Python 3.11 from python.org.
- **`drivion` is not recognized:** from source, activate the venv first
  (`.\.venv\Scripts\Activate.ps1`). In a packaged build, open PowerShell in the program
  folder and type `.\drivion.exe`.
- **`--doctor` shows nothing when run with `DrivionApp.exe`:** that program has no console.
  Use `drivion.exe` for commands.
- **A missing DLL or module in the packaged build:** run `drivion.exe --self-test`. It names
  what failed. Check that `_internal` is still beside the programs, then rebuild if needed.
- **Windows or antivirus blocks a packaged program:** the build isn't code-signed. Check
  that it's a build you trust, then allow it.
- **Drivion doesn't start at login:** run `drivion --autostart status`, and check that it's
  enabled in *Task Manager → Startup apps*. If you moved the folder, run
  `drivion --autostart on` again.
- **A settings error box appears at sign-in:** the message names the bad setting. Fix it in
  `%LOCALAPPDATA%\Drivion\config\settings.toml`.
- **"Drivion configuration error: ...":** fix the setting named in the message, or delete
  `settings.toml` to go back to the defaults.
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
  menu item, or end `python.exe` or `DrivionApp.exe` in Task Manager.

## License

MIT, see [LICENSE](LICENSE).
