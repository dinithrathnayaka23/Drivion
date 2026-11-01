# Recovery and troubleshooting

Start here whenever something isn't working:

```powershell
drivion --doctor
```

It checks the models, your face enrollment, liveness, AI keys, the microphone and Windows
voices, and prints the exact fix for each problem. It changes nothing, doesn't open the
microphone or camera, and sends nothing over the network.

## The tray icon is red (ERROR)

A part of Drivion failed, usually the microphone.

1. Fix the cause (see the notification or `drivion.log`).
2. Right-click the tray icon and choose **Recover from error**. Drivion returns to standby
   and starts listening again.
3. If it goes straight back to red, run `drivion --doctor`.

## I can't unlock Drivion

Drivion never controls your Windows sign-in, so you can't be locked out of your PC. You
can always sign in to Windows and do the following.

| What you see | What to do |
|---|---|
| "no face is enrolled" | `drivion --enroll-face` |
| "face not recognised" | Enroll again in good, even light. Check your score with `drivion --test-face`. |
| "the face data is damaged" or "different model" | `drivion --enroll-face` |
| "the head turned the wrong way" | Set `camera_mirrored = true` under `[face]` |
| "the head turn wasn't seen in time" | Turn further or sooner. Try `drivion --test-liveness`. |
| "the camera isn't available" | Close other camera apps, and check *Settings → Privacy & security → Camera* |
| "the lighting is too poor" | Face a light or a window |

## Re-enrolling your face

Do this if you're no longer recognised, for example after new glasses or a big change in
appearance.

- **From Drivion:** *Settings → Privacy → Enroll my face again*.
- **From PowerShell:** `drivion --enroll-face`.

The window asks for consent again. Your old templates are replaced only when enrollment
finishes, so cancelling keeps them.

## Deleting your face data

- **From Drivion:** *Settings → Privacy → Delete my face data*.
- **From PowerShell:** `drivion --delete-face`.

Drivion can't unlock until you enroll again.

## Settings problems

- **"Drivion configuration error" at startup:** the message names the bad setting. Fix it
  in `config/settings.toml`.
- **Going back to your previous settings:** the settings screen keeps a copy, so run:
  ```powershell
  Copy-Item config\settings.toml.bak config\settings.toml
  ```
- **Going back to the defaults:** delete `config/settings.toml`. Every setting has a default.
- **Comments disappeared from `settings.toml`:** saving from the settings screen rewrites
  the file without comments. `config/settings.example.toml` documents every option.
- **A change had no effect:** changes apply the next time Drivion starts.

## AI isn't answering

| What you hear | What to do |
|---|---|
| "no AI service is set up" | Add a real key in *Settings → AI provider* or in `.env`, then restart |
| "I couldn't reach any AI service" | Check your internet connection, then look at `drivion.log` for why each provider failed |

Simple commands keep working without AI. See [AI.md](AI.md).

## Starting completely fresh

This removes models, logs and face data, but not your settings or `.env`:

```powershell
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\Drivion"
drivion --download-models
drivion --enroll-face
```

## Getting logs

`%LOCALAPPDATA%\Drivion\logs\drivion.log` records state changes, each action and its
result (`drivion.audit`), and why each AI provider failed. API keys are redacted. It also
includes the text of your spoken commands, so read it before sharing it with anyone.
