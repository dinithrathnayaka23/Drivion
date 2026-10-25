# Wake word

Drivion listens for its wake word only while it is in **STANDBY**. It uses
[openWakeWord](https://github.com/dscripka/openWakeWord), which runs entirely on
your computer.

## How it works

```
microphone ──► MicrophoneSource ──► 80 ms frames ──► OpenWakeWordEngine ──► score 0..1
 (16 kHz mono)   (audio/source.py)                     (audio/wake_word.py)
                                                                │
                                         WakeWordDetector: score ≥ threshold
                                         and cooldown passed? ──► WAKE_WORD_DETECTED
                                                                     │
                                                    controller: STANDBY → VERIFYING
                                                    (the wake-word service is stopped
                                                     and the microphone is released)
```

- **The microphone is open only in STANDBY.** When Drivion leaves standby, the service
  stops and the microphone closes. The dashboard's microphone chip shows the device's
  real state, reported by the code that opens it.
- **Audio never leaves memory.** Frames are scored and discarded; nothing is recorded,
  saved or sent anywhere.
- **The wake word only starts verification.** It never grants access by itself.
  Detection moves Drivion to VERIFYING, and access still depends on face verification
  (Milestone 9).

## Why openWakeWord rather than Porcupine

Porcupine was the first choice, but in October 2026 Picovoice's FAQ said there are *"no
dedicated free or paid plans for personal or non-commercial use"*, with only a one-time
Free Trial. openWakeWord is open source (Apache-2.0 code), works offline, and needs no
account. The engine sits behind a `WakeWordEngine` interface, so a Porcupine adapter
can be added later without changing the rest of Drivion.

## Setup

```powershell
drivion --download-models        # one-time; about 3.6 MB from GitHub, SHA-256 checked
drivion --list-audio-devices     # optional: pick a specific microphone
drivion
```

Drivion never downloads anything automatically. Without the models it still runs: the
tray shows "Wake word unavailable", and you can still open Drivion from the tray.

## Settings (`config/settings.toml`)

```toml
[wake_word]
enabled = true
model = "hey_jarvis"          # built-in, or a path to your own .onnx
# phrase = "Wake up, Drivion" # text shown in the dashboard (for custom models)
sensitivity = 0.5             # higher = wakes more easily, but more false wakes
cooldown_s = 2.0              # ignore repeats for this many seconds
# input_device = 1            # index or part of a name from --list-audio-devices
```

Sensitivity maps to the engine threshold as `threshold = 1 - sensitivity`, clamped to
the range 0.05–0.95. The default of 0.5 matches openWakeWord's recommended threshold.

### Tuning

1. Start with `sensitivity = 0.5`. Say the phrase 10 times at normal volume, from where
   you usually sit.
2. If it misses more than 1 in 10, raise the sensitivity by 0.1.
3. Leave it running while you talk, watch videos or take calls. If it wakes without the
   phrase more than about once an hour, lower the sensitivity by 0.1.
4. The log (`%LOCALAPPDATA%\Drivion\logs\drivion.log`) records every detection with its
   score, for example `Wake word detected (score 0.93)`.

## Training "Wake up, Drivion"

The built-in `hey_jarvis` model is a stand-in for development. To train your own phrase:

1. Open openWakeWord's automatic training notebook in Google Colab. It's linked from the
   *Training New Models* section of the
   [openWakeWord README](https://github.com/dscripka/openWakeWord#training-new-models).
2. Set the target phrase to `wake up drivion`. If that produces weak results, try a
   phonetic spelling such as `wake up driv ee on`.
3. Run the notebook. It generates synthetic speech and trains a model in under an hour.
4. Download the `.onnx` file it produces, and put it in `%LOCALAPPDATA%\Drivion\models\`.
5. Configure it:
   ```toml
   [wake_word]
   model = "C:/Users/<you>/AppData/Local/Drivion/models/wake_up_drivion.onnx"
   phrase = "Wake up, Drivion"
   ```
6. Repeat the tuning steps above.

## Limits and licensing

- **Licensing:** the pre-trained openWakeWord models (including `hey_jarvis`) are
  licensed **CC BY-NC-SA 4.0**. That's fine for personal use, not for commercial use.
- **English only.** Recognition can be weaker with strong accents or background noise.
- **Resources:** measured on Windows 11 (MSI GF63), the Drivion process uses about 9%
  of one CPU core and about 245 MB of memory while listening in standby.
- **Sleep:** when Windows itself sleeps, nothing listens, so the wake word cannot wake
  the PC.
- **Package status:** openWakeWord 0.6.0 (February 2024) is the latest release, which is
  why the version is pinned exactly.
