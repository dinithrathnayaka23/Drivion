# Wake word

Drivion listens for **"Hey Drivion"** only while it is in **STANDBY**. Everything runs on
your computer. There are two engines:

| `wake_word.engine` | Phrase | Training | CPU |
|---|---|---|---|
| `whisper` (default) | "Hey Drivion" | None | Idle in silence; runs Whisper whenever someone speaks |
| `openwakeword` | "Hey Jarvis", or a model you train | Needed for your own phrase | Steady and low |

## The `whisper` engine

`audio/spoken_wake.py` works in three steps. Silero VAD finds a short burst of speech,
Whisper transcribes it, and the burst counts if it says "hey" followed by the name. Whisper
doesn't know the word "Drivion", so it writes "Drivian", "Dravian" or "Drivy On". The name
goes through the same fuzzy match as commands, which excludes real words like "driving". A
real voice drifted further, to "Drubian", "Tribune" and "Drew Bien", so a name also counts if
its consonants follow the same pattern: D or T, R, V or B, then N.

Measured with the real `base.en` model and both Windows voices on 3 November 2026:

| Measure | Result |
|---|---|
| "Hey Drivion" recognised, normal level | 23 of 24 |
| "Hey Drivion" recognised, quiet (peak 3,500 of 32,767) | 22 of 24 |
| "Hey Drivion" recognised, very quiet (peak 900) | 19 of 24 |
| Lookalike phrases that woke it, at any level | 0 of 40 |
| Time to transcribe a burst | about 0.45 s |

These are synthetic voices, so your own results may differ. A false wake only starts face
verification, so it can't unlock anything.

Giving Whisper the phrase as a hint looks better (30 of 30), but it then "hears" Drivion in
similar names: 9 of 40 lookalikes woke it. That's why the engine doesn't use a hint.

A short phrase is easy to lose on a laptop microphone, so the engine also counts any sound
clearly above the room's background, boosts quiet audio, and joins two bursts within 1.5
seconds, because a pause after "hey" can split the phrase in two.

To see what Drivion hears, run `drivion --test-wake`. It listens for 30 seconds and shows each
transcript on screen. Nothing is saved or logged.

`sensitivity` sets how speech-like a sound must be before Whisper checks it. Transcripts
stay in memory and are never logged or saved.

## The `openwakeword` engine

[openWakeWord](https://github.com/dscripka/openWakeWord) scores every 80 ms of audio with a
small trained model.

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
- **Audio never leaves memory.** It's checked and discarded; nothing is recorded, saved or
  sent anywhere.
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
engine = "whisper"            # or "openwakeword"
model = "hey_jarvis"          # openwakeword only: built-in, or a path to your own .onnx
# phrase = "Hey Drivion"      # text shown in the dashboard
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

## Training your own phrase

This is optional. It gives the `openwakeword` engine a phrase of your own, with steady CPU
use while people talk:

1. Open openWakeWord's automatic training notebook in Google Colab. It's linked from the
   *Training New Models* section of the
   [openWakeWord README](https://github.com/dscripka/openWakeWord#training-new-models).
2. Set the target phrase to `hey drivion`. If that produces weak results, try a phonetic
   spelling such as `hey driv ee on`.
3. Run the notebook. It generates synthetic speech and trains a model in under an hour.
4. Download the `.onnx` file it produces, and put it in `%LOCALAPPDATA%\Drivion\models\`.
5. Configure it:
   ```toml
   [wake_word]
   engine = "openwakeword"
   model = "C:/Users/<you>/AppData/Local/Drivion/models/hey_drivion.onnx"
   phrase = "Hey Drivion"
   ```
6. Repeat the tuning steps above.

## Limits and licensing

- **Licensing:** the pre-trained openWakeWord models (including `hey_jarvis`) are
  licensed **CC BY-NC-SA 4.0**. That's fine for personal use, not for commercial use.
- **English only.** Recognition can be weaker with strong accents or background noise.
- **Resources:** with `openwakeword`, measured on Windows 11 (MSI GF63), the Drivion process
  uses about 9% of one CPU core and about 245 MB of memory in standby. The `whisper` engine
  keeps the speech model loaded, so it uses more memory, and more CPU while people talk.
- **Long sentences:** the `whisper` engine checks up to 3 seconds at a time, so the phrase can
  be missed in the middle of a longer sentence. Say it on its own.
- **Sleep:** when Windows itself sleeps, nothing listens, so the wake word cannot wake
  the PC.
- **Package status:** openWakeWord 0.6.0 (February 2024) is the latest release, which is
  why the version is pinned exactly.
