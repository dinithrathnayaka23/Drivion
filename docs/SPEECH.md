# Speech: commands and spoken replies

While the dashboard is open (**ACTIVE**), Drivion listens for spoken commands,
transcribes them on your computer, and answers aloud using a Windows voice.

## How it works

```
microphone (64 ms frames) ─► Drivion speaking? ─yes─► ignore (+0.4 s echo tail)
                                  │ no
                                  ▼
                      Silero VAD: is this speech?        (speech/vad.py)
                                  ▼
          UtteranceRecorder: speech start … 0.8 s silence  (speech/recorder.py)
                                  ▼
               faster-whisper base.en, CPU int8, offline   (speech/stt.py)
                                  ▼
       CommandProcessor: history + reply + speak it        (core/commands.py)
```

- **One thread, one step at a time** (`speech/listener.py`). While Drivion transcribes or
  speaks, it isn't also recording, so its own voice is never transcribed as a command.
- **The microphone is open only in ACTIVE.** In STANDBY only the wake-word listener has it;
  the two never run at the same time.
- **Silence timeout:** if nobody speaks for `command_timeout_s` (default 20 s), Drivion
  says so and returns to standby. Drivion talking restarts the timer.
- **Hallucination filter:** Whisper sometimes "hears" words such as *"you"* in silence.
  Segments it rates as probably not speech (`no_speech_prob > 0.6`) are dropped, and
  Drivion replies *"Sorry, I didn't catch that."*
- **Replies (Milestone 5):** Drivion repeats what it heard and says it can't act on
  commands yet. Milestone 6 adds command understanding behind the same interface.

## Setup

```powershell
drivion --download-models   # adds the speech model (base.en, ~150 MB, pinned revision)
drivion --list-voices       # optional: choose a Windows voice
drivion
```

Without the speech model Drivion still works: the tray shows "Voice commands
unavailable", and the dashboard and wake word keep working.

## Settings (`[voice]` in `config/settings.toml`)

| Setting | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Listen for commands while active |
| `stt_model` | `"base.en"` | `tiny.en` (fastest), `base.en`, `small.en` (most accurate, ~480 MB) |
| `speech_threshold` | `0.5` | Raise it if background noise starts "commands" |
| `end_silence_s` | `0.8` | Pause length that ends a command; raise it if you get cut off mid-sentence |
| `max_command_s` | `15` | Longest single command |
| `command_timeout_s` | `20` | No speech for this long returns Drivion to standby |
| `tts_engine` | `"windows"` | `"none"` shows replies without speaking them |
| `tts_voice` | default voice | Part of a voice name, e.g. `"Zira"` |
| `tts_rate` / `tts_volume` | `0` / `100` | −10…10 / 0…100 |
| `greeting` | `"I'm listening."` | Spoken when the dashboard opens; `""` for silence |

If you change `stt_model`, run `drivion --download-models` again.

## Measured performance (Windows 11, MSI GF63, CPU only)

| What | Result |
|---|---|
| First activation (model load + mic open) | about 1.4 s; later activations reuse the loaded model |
| Listening, waiting for speech | about 3.4% of one CPU core |
| Transcribing a 2–4 s command | about 0.5–1.2 s |
| Memory added by the speech model | about 180 MB |

## Privacy

- Audio is processed in memory and discarded. Nothing is recorded to disk or sent anywhere.
- Command text is kept only in the session history, in memory (see `ui.history_limit`).
- The log records each command as it was transcribed, for troubleshooting. That log file
  is local and is never committed to Git.

## Limits

- English models only (`*.en`).
- Accuracy depends on your microphone, room and accent. Try `small.en` if `base.en`
  mishears you.
- No barge-in: you can't interrupt Drivion while it is speaking; wait for it to finish.
- "Drivion, go to sleep" is transcribed but not acted on until Milestone 6. Use the
  window, the tray, or the silence timeout to return to standby.
- GPU (CUDA) acceleration isn't enabled. It would need CUDA 12 and cuDNN 9.
