# Actions and safety

Milestone 7 makes Drivion actually do things, inside a safety layer that decides what may
run, when, and whether it must ask you first.

```
spoken command ─► intent (validated, docs/COMMANDS.md)
               ─► SafeExecutor  (safety/executor.py)
                    1. registered action?          no  → "That isn't something I'm allowed to do."
                    2. Drivion unlocked (ACTIVE)?   no  → refused (fail closed)
                    3. HIGH risk?                   yes → "Are you sure…? Say yes or no."  (waits 15 s)
                    4. run the handler (crash-proof) → verified result
               ─► reply + history + audit log
```

## The action list

Defined in `actions/handlers.py` and registered in `ActionRegistry`. Nothing else can run.

| Action | Risk | Confirmation | How it's done | How success is checked |
|---|---|---|---|---|
| Set/change volume, mute/unmute | LOW | – | Windows Core Audio (pycaw) | Level and mute state read back |
| Set/change brightness | LOW | – | WMI, built-in screens only | Level read back |
| Open app | LOW | – | `os.startfile` on the app's allowlisted `launch` | Waits up to 5 s for its window |
| Open website | LOW | – | Allowlisted `https://` address in your default browser | Can't be checked; the reply says "Opening…" |
| Open folder | LOW | – | Allowlisted folder in File Explorer | The folder must exist |
| Minimize/restore app | LOW | – | The app's own windows only, found by `process` name | Window state read back |
| Take screenshot | LOW | – | All monitors, saved as PNG in `actions.screenshot_dir` | The file must exist |
| Lock Windows | MEDIUM | – | `LockWorkStation`; unlock with your Windows password | Windows' return value |
| Sleep | **HIGH** | **yes** | `SetSuspendState` after 3 s | Can't be checked (see Modern Standby below) |
| Restart | **HIGH** | **yes** | `shutdown.exe /r /t 10` | `shutdown.exe` accepted it |
| Shut down | **HIGH** | **yes** | `shutdown.exe /s /t 10` | `shutdown.exe` accepted it |

"Success" means the effect was **verified** where Windows makes that possible. Otherwise
the reply only says what was requested, for example *"I've asked Windows to open vs
code."*

## Confirmation rules (sleep, restart, shut down)

- Drivion asks *"Are you sure you want me to shut down the computer? Say yes or no."*
- Only an explicit **yes** within `actions.confirmation_timeout_s` (15 s) runs it.
- **No**, **cancel**, **"don't…"**, silence, or *any other command* drops the request.
  An unclear reply is never treated as consent.
- Authorization is checked again at the moment you say yes.
- Restart and shut down happen after `actions.power_delay_s` (10 s). Saying **cancel** in
  that time aborts them (`shutdown /a`). Windows also shows its own notice.
- *"Drivion, go to sleep"* only returns Drivion to standby. It is never a power action.

## What Drivion will not do

- Run anything that isn't in the action list, or open anything that isn't in your
  allowlist (`[commands]` in the config).
- Pass arguments to programs. A `launch` entry containing arguments or shell symbols
  (`/c`, `-x`, `&`, `|`, `%`, `*`, quotes…) is rejected at startup.
- Act while Drivion is in standby, verifying, or in an error state.
- Delete files, change Windows settings beyond volume and brightness, use credentials,
  ask for administrator rights, or run hidden in the background.

## The audit log

Every decision is written to `%LOCALAPPDATA%\Drivion\logs\drivion.log` under
`drivion.audit`, for example:

```
DONE SET_VOLUME {"percent":40} (risk LOW, verified, 12 ms): Volume set to 40%.
PENDING SHUTDOWN_COMPUTER (risk HIGH): waiting for confirmation
DROPPED SHUTDOWN_COMPUTER: the user said no
REFUSED SET_VOLUME: not authorized
```

## Sleep on Modern Standby laptops

Many recent laptops, including the MSI GF63 this was developed on, use **Modern Standby
(S0 Low Power Idle)** and have no classic S3 sleep (check with `powercfg /a`). On these,
Windows may refuse `SetSuspendState`. Drivion then says *"Windows didn't go to sleep"*
rather than pretending. There's no documented API to enter Modern Standby directly. If you
want a voice power-saving command, set:

```toml
[actions]
sleep_method = "hibernate"   # saves your session to disk and powers off; slower to resume
```

## Testing safety

- Automated tests use **fake** backends for every action (`tests/action_fakes.py`).
- The test suite also sets `DRIVION_POWER_DRY_RUN=1`. With it set, the real power backend
  refuses every call, so a mistaken test can't sleep, restart or shut down the PC. Tests
  check this refusal for all four power calls.
- The real Windows backends are only tested with read-only calls. A screenshot is taken
  to a temporary file and deleted straight away.

## Adding an app

```toml
[commands.apps.spotify]
aliases = ["music"]
launch = "C:/Users/you/AppData/Roaming/Spotify/Spotify.exe"
process = "Spotify.exe"     # find it in Task Manager → Details
```

The Milestone 6 shorthand `spotify = ["music"]` still works, but such an app can only be
*named*, not opened, until it has a `launch` entry.

## Known limits

- Brightness only works on built-in laptop screens (WMI). External monitors report
  "I can't change the brightness of this screen."
- Microsoft Store apps such as Calculator host their windows in a different process, so
  minimizing or restoring them may report "isn't open".
- "Open website" can't confirm the page loaded.
- Restoring a window can't always bring it to the front, because Windows limits which
  programs may steal focus.
