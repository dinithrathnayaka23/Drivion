# Face verification

After the wake word, Drivion checks that the person at the camera is you before it opens
the dashboard. Everything runs on your PC, and nothing is uploaded.

```
wake word ─► VERIFYING: camera on ─► YuNet: find faces ─► quality checks ─► SFace: 128-number embedding
                                                                                  │
                    best cosine similarity to your encrypted templates  ◄──────────┘
                                                                                  │
          3 frames ≥ 0.55 (and more matches than unknowns) ─► ACTIVE   (camera off)
          otherwise ─► "Access denied: <reason>" ─► STANDBY            (camera off)
```

## Setup

```powershell
drivion --download-models   # adds YuNet (0.2 MB) and SFace (37 MB), SHA-256 checked
drivion --enroll-face       # asks for consent, then takes 8 samples (~10 s)
drivion --test-face         # optional: shows your live score against the threshold
drivion                     # say the wake word: Drivion now checks your face
```

To remove your face data: `drivion --delete-face`. Drivion then can't unlock until you
enroll again.

## No IR camera? What that means

Most laptops, including the MSI GF63, have an ordinary RGB webcam and no infrared camera.

- **Recognition works normally.** Telling you apart from other people uses colour images.
  That's what YuNet and SFace do, and what the measurements below are based on.
- **Spoofing is the gap.** Windows Hello uses IR and depth to check that a real face is
  present. An RGB camera can't, so **a good photo or video of you could pass face matching
  alone**. Milestone 10 adds a liveness challenge to make that much harder, but it can't
  make an RGB webcam as strong as Windows Hello.
- **That's why Drivion only protects its own features.** It never replaces or bypasses
  your Windows sign-in, and power actions still need a spoken "yes".

## How the threshold was chosen

The default `similarity_threshold = 0.55` comes from a measurement, not a guess. The tool
is `tools/face_threshold_eval.py`.

- **Dataset:** the ORL / AT&T Database of Faces (credit: Olivetti Research Laboratory,
  Cambridge, 1992–94). It has 400 photos of 40 people, with varying lighting, expressions
  and glasses.
- **Protocol:** like Drivion's. For each person, 5 photos are the enrolled templates and
  the other 5 are attempts. The score is the best cosine similarity over the templates.
- **Results:** 400 of 400 faces detected; 200 genuine and 7,800 impostor attempts.

| | lowest | 5th percentile | median | highest |
|---|---|---|---|---|
| Genuine (you vs your templates) | **0.575** | 0.789 | 0.912 | – |
| Impostor (someone else) | – | – | 0.156 | **0.466** |

| Threshold | False accepts | False rejects |
|---|---|---|
| 0.363 (OpenCV's usual value) | **0.85%** (66 of 7,800) | 0% |
| 0.45 | 0.08% (6) | 0% |
| **0.50–0.55** | **0%** | **0%** |
| 0.60 | 0% | 0.5% |
| 0.70 | 0% | 2.5% |

0.55 sits clearly above the highest impostor score (0.466) and below the lowest genuine
one (0.575). On top of that, Drivion needs 3 matching frames, which makes a false accept
much less likely again.

**Your camera, lighting and face are different from this dataset**, so check with
`drivion --test-face`:

- If your score is usually well above 0.55 (for example 0.7–0.9), keep the default.
- If you're often rejected in normal light, first **enroll again in good, even light**.
  Only then consider lowering the threshold a little. Below 0.45 strangers start to be
  accepted.

To repeat the measurement, download `att_faces.zip` from
https://www.cl.cam.ac.uk/research/dtg/attarchive/facedatabase.html, extract it, and run:

```powershell
python tools/face_threshold_eval.py "$env:LOCALAPPDATA\Drivion\models" <extracted folder>
$env:DRIVION_FACE_DATASET = "<extracted folder>"; pytest tests/test_face_real.py
```

## The verification rules

- Only frames that pass the **quality checks** count:
  - exactly one face
  - at least 90 px wide
  - not too dark or too bright
  - sharp
  - roughly facing the camera

  Other frames are skipped. They count neither for nor against you, so bad light can't
  make you look like a stranger.
- Unlocking needs **3 matching frames** (`required_matches`), and more matches than
  unknown-face frames.
- **6 clear unknown-face frames end the attempt early**, so a stranger can't keep trying
  until the timeout.
- **Two people in view is never a match**, even if one of them is you.
- When an attempt fails, Drivion says why: face not recognised, no face, more than one
  face, poor lighting, too blurry or far, camera unavailable, not enrolled, or models
  missing.
- Each result is tied to its attempt number, so a late answer can't unlock a newer
  attempt. If no answer arrives in time (`verification_timeout_s`), access is denied.

## Privacy and storage

- **What's stored:** 8 *embeddings* (128 numbers each), not photos. An embedding can't be
  turned back into a picture of you, but it's still biometric data.
- **Encryption:** stored in `%LOCALAPPDATA%\Drivion\face\templates.bin` and encrypted with
  Windows DPAPI under your Windows account. A copied file can't be decrypted on another
  account or PC, and a tampered file is rejected.
- **Optional crops:** with `store_raw_images = true`, small aligned face crops
  (112×112) are also kept, encrypted the same way. The default is off.
- **Camera use:** the camera is on only while enrolling, testing or verifying, and the
  dashboard's camera chip shows it. The preview is on screen only and never saved.
- **Git:** face data is outside the repository and git-ignored either way.

## Enrollment and recovery

- **Enrollment asks for consent first.** Start stays disabled until you tick the consent
  box.
- **Each sample must resemble the others,** so someone stepping in front of the camera
  doesn't get mixed into your templates.
- **Re-enrolling** replaces the old templates (the window warns you).
- **If you're no longer recognised** (new glasses, different lighting), run
  `drivion --enroll-face` again.
- **If the templates are damaged or from an old model version,** Drivion tells you to
  enroll again.
- **Locked out entirely?** Drivion never controls your Windows sign-in, so you can always
  sign in to Windows and re-enroll. `drivion --simulate` can also unlock the dashboard
  for development.

## Tests

- **Decision logic** is tested with scripted frames and embeddings, so no camera is
  needed: thresholds, early rejection, quality skipping, multiple faces, camera failure
  and cancelling.
- **Encrypted storage** is tested for the round trip, tampering, model mismatch and
  deletion.
- **The enrollment window** is tested for consent gating, a full enrollment, cancelling
  and test mode.
- **The real models** are tested on a picture with no face. With the dataset, they're
  also tested on 40 real people and in full end-to-end verification.

## Limits

- **Liveness:** not yet (Milestone 10), so a photo of you can pass face matching.
- **One person:** only one person can be enrolled.
- **Accuracy:** it drops with heavy backlight, very low light, strong angles, and large
  changes in appearance.
- **Dataset vs webcam:** the threshold measurement used greyscale studio photos. Webcam
  conditions vary, so use `--test-face`.
