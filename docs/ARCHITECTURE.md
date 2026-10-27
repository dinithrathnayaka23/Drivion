# Drivion Architecture & Plan

## 1. Architecture overview

Drivion is a **modular monolith**: one Python process and one repository, split into
packages with one responsibility each. Packages talk through typed interfaces
(`typing.Protocol`) so that real hardware/AI implementations can be swapped for
fakes in tests.

```
               ┌──────────────────────── Drivion process ────────────────────────┐
               │                                                                 │
 microphone ──►│ audio (capture + wake word) ──► core (state machine, lifecycle) │
               │                                   │        ▲                    │
   webcam ────►│ vision (face verify, liveness) ◄──┘        │ Qt signals         │
               │                                   │        │                    │
               │ speech (STT/TTS) ──► intents (rules → LLM fallback)             │
               │                          │                                      │
               │                          ▼                                      │
               │              safety (policy, confirmation)                      │
               │                          │                                      │
               │                          ▼                                      │
               │              actions (registry → Windows handlers)              │
               │                                                                 │
               │ ui (dashboard, tray)   config (settings, secrets, paths, logs)  │
               └─────────────────────────────────────────────────────────────────┘
```

Key rules:

- **The UI thread only draws.** Audio, camera and model inference run in worker
  threads and send results to the UI with Qt signals.
- **The core state machine is the only thing that decides what happens next.**
  Workers report events ("wake word heard", "face verified"); the core decides
  whether the event is valid in the current state.
- **The LLM never executes anything.** It can only return a choice from the action
  registry plus parameters. Those parameters are validated against a pydantic schema
  and then checked by the safety policy before anything runs.
- **Fail closed.** If the camera, the model or the verification step is unavailable,
  protected actions are denied. They are never allowed by default.

## 2. Directory tree (target)

```
Drivion/
├── pyproject.toml            dependencies, entry point, pytest config
├── .env.example              secret placeholders (real .env is git-ignored)
├── config/
│   └── settings.example.toml copy to settings.toml (git-ignored)
├── docs/ARCHITECTURE.md
├── src/drivion/
│   ├── app.py, __main__.py   entry point                              [M1]
│   ├── logging_setup.py      console + rotating file, secret redaction [M1]
│   ├── config/               settings.py, secrets.py, paths.py         [M1]
│   ├── core/                 state machine, lifecycle, single instance [M2]
│   ├── ui/                   main window, tray, dashboard, settings    [M1→M3]
│   ├── audio/                microphone capture, wake word             [M4]
│   ├── speech/               speech-to-text, text-to-speech            [M5]
│   ├── intents/              schemas, rule parser, LLM parser          [M6, M8]
│   ├── actions/              registry + Windows handlers               [M7]
│   ├── safety/               risk policy, authorization, confirmation  [M7]
│   ├── llm/                  provider interface + cloud provider       [M8]
│   └── vision/               camera, detector, embedder, templates,
│                             liveness                                  [M9, M10]
└── tests/
```

Personal data (logs, and face templates later) is stored in `%LOCALAPPDATA%\Drivion`,
not in the repository.

## 3. Application states (implemented in M2)

Code: `core/state.py` (rules), `core/controller.py` (event → transition decisions).
Background threads never change state directly. They call `controller.post_event()`,
which queues the event onto the Qt main thread, so events are handled one at a time,
in order. Each verification attempt gets an id, and results carrying an old id are
discarded, so a late "face OK" from a timed-out attempt can't unlock a newer one.

| State | Meaning | Allowed next states |
|---|---|---|
| STANDBY | UI closed, only the wake-word listener runs | VERIFYING, SHUTTING_DOWN, ERROR |
| VERIFYING | Camera on, face + liveness check running | ACTIVE, STANDBY (fail/timeout), ERROR, SHUTTING_DOWN |
| ACTIVE | Dashboard open, commands accepted | SLEEPING, ERROR, SHUTTING_DOWN |
| SLEEPING | Tearing down camera/STT/UI, then back to standby | STANDBY, ERROR, SHUTTING_DOWN |
| ERROR | A subsystem failed; show the reason, allow recovery | STANDBY, SHUTTING_DOWN |
| SHUTTING_DOWN | Releasing every resource; the process exits | (terminal) |

### Standby, exit, lock and sleep are four different things

| Phrase / action | What happens | Drivion process | Windows |
|---|---|---|---|
| "Drivion, go to sleep" (**app standby**) | Dashboard closes; camera and STT stop | Keeps running; only the wake word listens | Unaffected |
| Tray → Exit Drivion (**app exit**) | All services stop | Ends; "Wake up" no longer works | Unaffected |
| "Lock Windows" (**Windows lock**) | Lock screen appears | Keeps running | Session locked; you need your Windows password/PIN |
| "Put my computer to sleep" (**Windows sleep**) | The PC suspends after you confirm | Frozen along with everything else | Low-power state; the mic is off, so the wake word cannot wake the PC |

### Command understanding (M6)

`transcript → normalize → whole-sentence rules → pydantic-validated Intent → responder`.
All intents live in `intents/schemas.py` as one discriminated union (`INTENT_ADAPTER`).
Open targets must resolve through the allowlist `Catalog` (`[commands]` in the config).
The responder runs in the command-listener thread. *Go to sleep* posts the same
`SLEEP_REQUESTED` event as the window button. In Milestone 8 the LLM's output will be
validated by the same `INTENT_ADAPTER`, so it can only select registered intents. See
[COMMANDS.md](COMMANDS.md).

### Per-state services (M4, M5)

The controller runs some services only in one state. The wake-word listener runs in
STANDBY, and the command listener (VAD → Whisper) runs in ACTIVE. The old state's
services are stopped before the new state's start, so the two never hold the microphone
at the same time. The speech output (`WindowsSpeaker`) is a session service, so a reply
can finish after Drivion returns to standby.

### Dashboard data flow (M3)

`core/activity.py` holds an `ActivityFeed`, the single source of truth for what the
dashboard shows: microphone and camera state, and command history. Subsystems report to
it from any thread, the feed relays updates to the main thread, and the window only
displays them. Only the code that actually opens a device may report it as ACTIVE, so
the indicators can't claim a device is off while it is in use. History is kept in
memory only, has a size limit (`ui.history_limit`), and is never written to disk.

The animated orb (`ui/widgets/orb.py`) runs its 30 fps timer only while visible, so a
hidden dashboard in standby costs no animation CPU. Setting `ui.animations = false`
draws a static indicator instead.

## 4. Milestones

| # | Milestone | Main deliverable |
|---|---|---|
| **1** | **Scaffolding** ✅ | Config validation, secrets, logging, entry point, minimal window, tests |
| 2 | Core lifecycle ✅ | State machine with transition rules, single-instance lock, worker-thread infrastructure, tray icon with Exit, simulated events |
| 3 | Dashboard UI ✅ | Animated indicator, live state, mic/camera indicators, history panel (driven by fake events) |
| 4 | Wake word ✅ | Microphone capture, Porcupine custom keyword, standby loop, mocked-audio tests |
| 5 | Speech ✅ | faster-whisper command capture (silence/timeout handling), Windows TTS |
| 6 | Intents (offline) ✅ | Pydantic intent schemas, rule-based parser with aliases, help/repeat/cancel |
| 7 | Actions + safety | Action registry, risk levels, confirmation flow, allowlisted app launch, volume, brightness, lock, screenshot, window control, power actions (confirmed and mocked in tests) |
| 8 | LLM | Provider interface, one cloud provider, structured intent fallback, general Q&A, network-error handling |
| 9 | Face verification | Consent-based enrollment, YuNet detection + SFace embeddings, encrypted local templates, threshold calibration |
| 10 | Liveness | Challenge-response (blink/turn head), honest limits documented |
| 11 | Integration | End-to-end flow, settings dialog, recovery procedures |
| 12 | Packaging | PyInstaller build, startup at login (Task Scheduler), final README |

## 5. Dependency and compatibility decisions

| Need | Choice | Why |
|---|---|---|
| Python | **3.11** in a `.venv` | Has wheels for faster-whisper/ctranslate2, onnxruntime, pvporcupine and PySide6. Your default `python` is 3.14, which is too new for some of these, so always use the venv. |
| UI | PySide6 6.9.x | The official Qt binding and LGPL-licensed; `QThread` plus signals covers the threading model |
| Config / schemas | pydantic v2 + pydantic-settings | One validation library for config, secrets, intent parameters and action schemas |
| Config format | TOML (stdlib `tomllib`) | Readable and supports comments; no extra dependency |
| Wake word | **openWakeWord 0.6.0** (decided in M4) | Porcupine was checked first, but Picovoice's FAQ (October 2026) lists no plans for personal or non-commercial use, only a one-time trial. openWakeWord is offline, open source and needs no account. It sits behind a `WakeWordEngine` interface so Porcupine could be added later. See [WAKE_WORD.md](WAKE_WORD.md). |
| Audio capture | sounddevice + numpy | PortAudio wheels for Windows, and the same capture code will serve speech-to-text in M5 |
| STT | **faster-whisper 1.2.1**, `base.en`, CPU int8 (M5) | Runs offline and is accurate (0.5–1.2 s per command here). Models come from pinned Hugging Face revisions. Its bundled Silero VAD detects where commands start and end, so no extra download. CUDA can come later. See [SPEECH.md](SPEECH.md). |
| TTS | **Windows SAPI via comtypes** (M5) | Needs no model download, and the voices are already installed. Piper is deferred; `tts_engine` only accepts `windows` or `none` until it exists. |
| Face | OpenCV `FaceDetectorYN` (YuNet) + `FaceRecognizerSF` (SFace) | Both are in core OpenCV ≥4.5.4 as small ONNX models, so we avoid dlib/face_recognition build problems |
| Template protection | Windows DPAPI via `ctypes` | Encrypts templates to your Windows account with no extra package |
| Volume | pycaw | Core Audio API |
| Brightness | WMI (`WmiMonitorBrightnessMethods`) through a fixed PowerShell command | Works on laptop panels; external monitors are often unsupported |
| Tests | pytest + pytest-qt | Qt widgets can be tested offscreen |
| Packaging | PyInstaller (to evaluate against pyside6-deploy in M12) | |

## 6. Risks and hardware assumptions

- **Hardware assumed:** MSI GF63 laptop running Windows 11, built-in 720p RGB webcam
  (no IR camera), built-in array microphone, NVIDIA GPU (unused until a later
  CUDA option).
- **Spoofing:** An RGB webcam with face matching **cannot** reliably stop a photo or
  video replay. Challenge-response liveness raises the effort an attacker needs, but
  it is not Windows Hello. Drivion therefore gates only its own features. It never
  replaces or bypasses Windows login.
- **Wake-word licensing:** this was resolved in M4 by switching to openWakeWord. Its
  pre-trained models are licensed CC BY-NC-SA 4.0, which allows personal use only.
- **False wakes or missed wakes:** Sensitivity is configurable and is tuned manually
  in your room.
- **Brightness:** Unsupported on many external monitors, so Drivion will report this
  instead of pretending it worked.
- **Sleep vs hibernate:** `SetSuspendState` may hibernate if hibernation is enabled.
  Modern Standby laptops behave differently. Both get verified manually in M7.
- **Resource use:** An always-on mic stream plus Whisper on the CPU uses battery.
  Standby runs only the wake-word engine.
- **Privacy:** The camera runs only in VERIFYING, the mic stream runs only for the
  wake word in standby, and the UI shows indicators whenever either is in use.
