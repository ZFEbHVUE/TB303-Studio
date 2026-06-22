# TB-303 Studio — Bass Line (acid synth + steampunk skin)
**by Stéphane "ZFEbHVUE"**

An *acid* bass synthesizer inspired by the Roland TB-303, written in pure Python
(NumPy), with a graphical interface "skinned" by an image (a steampunk panel).
The audio engine runs oscillator → resonant low-pass filter → envelopes →
16-step sequencer, and the interface overlays functional controls onto the image.

> **Technical honesty.** This is **not** a component-accurate clone of the TB-303
> circuit. It is a **character emulation**: it reproduces the spirit (anti-aliased
> saw/square oscillator, resonant ~18 dB/oct ladder filter swept by the envelope,
> accent, slide, sequencer with swing) but the original schematic is approximated,
> not copied. No Roland branding, logo, or sample is used — the panel design is original.
>
> 
![TB303-Studio GUI](docs/gui_main.png)

## Table of contents

1. [Folder contents](#folder-contents)
2. [Requirements and installation](#requirements-and-installation)
3. [Quick start](#quick-start)
4. [The interface](#the-interface)
5. [Programming a pattern](#programming-a-pattern)
6. [Save and recall a project (`.tb303`)](#save-and-recall-a-project-tb303)
7. [Knob reference](#knob-reference)
8. [Menus: Scale, Play Mode, Preset](#menus-scale-play-mode-preset)
9. [The synthesis engine](#the-synthesis-engine)
10. [Pattern notation](#pattern-notation)
11. [Using the engine as a library](#using-the-engine-as-a-library)
12. [The skin system (image + coordinate map)](#the-skin-system-image--coordinate-map)
13. [Creating a new skin](#creating-a-new-skin)
14. [Troubleshooting](#troubleshooting)
15. [File-by-file notes](#file-by-file-notes)

---

## Folder contents

| File | Role |
|---|---|
| `tb303.py` | Synthesis engine + sequencer (NumPy only). No GUI dependency. |
| `tb303_studio.py` | Graphical "skin" interface: loads the image and overlays the controls. |
| `tb303_skin.png` | Skin image (steampunk panel, with the step cells and value fields blanked). |

All **three files must sit in the same folder**. `tb303_studio.py` imports `tb303.py`
and loads `tb303_skin.png` by default.

---

## Requirements and installation

### Dependencies

| Package | Why | Required? |
|---|---|---|
| **NumPy** | Audio synthesis | Yes |
| **Pillow** (+ ImageTk) | Load and display the skin image | Yes (for the GUI) |
| **Tkinter** | Window and widgets | Yes (usually preinstalled) |
| **pygame** | Real-time audio playback (RUN/STOP) | Optional — without it, **SAVE WAV** still works |

### Installing — the golden rule

Install into the **same Python that runs the script**. The safest way:

```bash
python3 -m pip install numpy pillow pygame
```

Using `python3 -m pip` guarantees the packages land in the exact interpreter that
`python3 tb303_studio.py` uses — no need to wonder which environment you're in.

### Per platform

**Ubuntu / Debian (system Python).** The cleanest route is apt — it targets the
system `python3` and provides `ImageTk` (often missing with pip alone):

```bash
sudo apt install python3-numpy python3-pygame python3-pil python3-pil.imagetk python3-tk
```

> The **`python3-pil.imagetk`** package matters: it provides `ImageTk`. Without it,
> Pillow alone is not enough with Tkinter and the window won't display.

If pip refuses with "externally-managed-environment" (recent Ubuntu), add
`--break-system-packages` or use a virtualenv.

**conda (e.g. an `xtts` environment).** Activate the environment you launch the script
from, then install into it:

```bash
conda activate my_env
pip install pygame pillow numpy
```

**WSL / WSLg (Windows).** Audio goes through WSLg/PulseAudio. **No variables to set by
hand**: at startup, if `tb303_studio.py` detects `/mnt/wslg/PulseServer`, it
automatically wires `SDL_AUDIODRIVER=pulseaudio` and the correct `PULSE_SERVER`.

### Verify the install

```bash
python3 -c "import sys, numpy, PIL, pygame; print(sys.executable); print('pygame', pygame.__version__)"
```

If the printed path is your interpreter and no error appears, you're ready.

---

## Quick start

```bash
python3 tb303_studio.py
```

On launch, the interface already shows the demo pattern. Check the **status text**
(bottom of the window):

- **"Pret"** → the audio engine is active, RUN will play.
- **"pygame absent"** → install pygame for real-time sound (SAVE WAV already works).
- **"audio KO (…)"** → the audio engine failed to initialize; the message in
  parentheses explains why.

To load a different skin image:

```bash
python3 tb303_studio.py my_other_skin.png
```

---

## The interface

Everything is clickable directly on the image.

- **WAVEFORM (saw / sqr)** — selects the oscillator waveform (sawtooth or square).
- **Top 6 knobs** — TUNING, CUT OFF, RESONANCE, ENV MOD, DECAY, ACCENT.
- **Bottom 4 knobs** — TEMPO, DIST (distortion), VOLUME, SHUFFLE.
- **SCALE / PLAY MODE / PRESET** — three dropdown menus.
- **PATTERN 1–8** — eight independent pattern banks.
- **RUN / STOP** — loop playback / stop.
- **Keyboard** — click a key to place a note on the selected step.
- **ACCENT / SLIDE / OCT↓ / OCT↑ / REST** — modifiers for the selected step.
- **16-cell strip** — the sequencer's 16 steps; click a cell to select it (amber frame).
  Each cell shows its live note (e.g. `C2`, with `+` for accent, `~` for slide).
- **SAVE WAV / CLEAR / DEMO** — export to .wav / clear everything / reload the demo.

**Adjusting a knob:** mouse wheel over it, or click-and-drag vertically.

---

## Programming a pattern

1. **Click a cell** in the 16-step strip (it gets an amber frame).
2. **Click a key** on the keyboard → the note lands on that step, and the selection
   advances automatically to the next step. (So you can chain notes on the keyboard.)
3. To edit a specific step, select it, then:
   - **ACCENT** → accents the step (louder, filter opens more). Marked `+`.
   - **SLIDE** → glide to the next note (legato/portamento). Marked `~`.
   - **OCT↓ / OCT↑** → move the note down / up one octave.
   - **REST** → silence (clears the step's note).
4. **PATTERN 1–8**: eight banks. Switching banks saves the current one and loads the
   other — handy for A/B comparisons or building a track.
5. **CLEAR** empties the current pattern; **DEMO** reloads the example pattern.
6. **RUN** plays in a loop; you can turn the knobs **while playing** and the sound
   updates on each change.

---

## Save and recall a project (`.tb303`)

Beyond exporting audio (WAV), you can save the **entire editable state** to a
`name.tb303` project file and **reload it as-is** later — with exactly the same knob
positions and all parameters.

Via the **File** menu (top of the window) or shortcuts:

| Action | Menu | Shortcut |
|---|---|---|
| Save the project | File → Save project… | **Ctrl+S** |
| Reload a project | File → Open project… | **Ctrl+O** |
| Export audio | File → Export WAV… (or the SAVE WAV button) | — |

The `.tb303` file (human-readable JSON) contains: **all 10 knobs**, the **waveform**,
the **Scale / Play Mode / Preset** menus, the **current bank**, and the **8 full
pattern banks** (notes, accents, slides). Reopening it restores everything at once.

> Don't confuse them: **SAVE WAV** exports the *sound* (not editable); **Save project**
> stores the *session* (editable, replayable, tweakable).

---

## Knob reference

| Knob | Range | Default | Effect |
|---|---|---|---|
| **TUNING** | 400–480 | 440 | Fine global tuning (≈ ±1.5 semitones). Shifts everything's pitch, subtly. |
| **CUT OFF** | 0–1 | 0.40 | Filter cutoff frequency. Very audible: opens/closes the tone (30 Hz → 10 kHz). |
| **RESONANCE** | 0–1 | 0.10 | Resonant peak at the cutoff. Pushed high, gives the acid "squelch" (up to near self-oscillation). |
| **ENV MOD** | 0–1 | 0.12 | How much the envelope opens the filter on each note (the 303 "wow"). |
| **DECAY** | 0–1 | 0.40 | Length of the per-note filter sweep (≈ 0.04 → 1.6 s). |
| **ACCENT** | 0–1 | 0.30 | Intensity of accented steps. **Only affects steps marked `+`** (otherwise no effect — this is normal). |
| **TEMPO** | 60–200 | 130 | Tempo in BPM. |
| **DIST** | 0–1 | 0.00 | Saturation (tanh waveshaping) after the filter. Adds grit/growl. |
| **VOLUME** | 0–1 | 0.90 | Output level (playback **and** export). |
| **SHUFFLE** | 0–0.66 | 0.00 | Swing: offsets every other step for a shuffled groove. Most audible at 1/16. |

**The winning acid combo:** high RESONANCE (0.8–1.0) + low CUT OFF (~0.3) + high ENV MOD,
then sweep CUT OFF while it plays.

---

## Menus: Scale, Play Mode, Preset

**SCALE** (step rhythmic subdivision):

| Choice | Steps per beat |
|---|---|
| 1/8 | 2 |
| 1/8T | 3 (triplet) |
| 1/16 | 4 |
| 1/16T | 6 (triplet) |
| 1/32 | 8 |

**PLAY MODE** (playback order of the 16 steps): `Forward`, `Reverse`, `Fwd&Rev`
(back-and-forth), `Invert` (flips high/low), `Random`.

**PRESET** (quick starting points):

| Preset | Wave | Cutoff | Reso | EnvMod | Decay | Accent | Dist |
|---|---|---|---|---|---|---|---|
| Classic Bass | square | 0.40 | 0.10 | 0.12 | 0.40 | 0.30 | 0.00 |
| Acid | saw | 0.30 | 0.84 | 0.65 | 0.55 | 0.70 | 0.28 |
| Sub Bass | square | 0.24 | 0.06 | 0.06 | 0.55 | 0.30 | 0.00 |
| Rubber | saw | 0.36 | 0.45 | 0.35 | 0.45 | 0.45 | 0.00 |

---

## The synthesis engine

Signal chain, in order:

1. **Oscillator** — sawtooth or square, anti-aliased with **PolyBLEP** (no metallic
   aliasing on high notes).
2. **303-style low-pass filter** — a **4-stage ladder** whose **output is tapped at the
   3rd pole**, giving roughly an **18 dB/oct** slope (brighter and more nasal than a
   Moog's 24 dB/oct — the 303 signature). **Feedback comes from the 4th pole** (the phase
   shift needed to resonate), with **tanh saturation** on the input and the loop: the
   resonance can rise toward self-oscillation, and the saturation provides the grit.
3. **Filter envelope** — fast attack then a decay set by DECAY; how deeply it acts on
   the cutoff is set by ENV MOD. This creates the characteristic "wow" sweep.
4. **Amplitude envelope (VCA)** — opens/closes the level per note (gate), with accent on
   marked steps.
5. **Accent** — on `+` steps, boosts both the level and the filter opening.
6. **Slide** — on `~` steps, pitch glide toward the next note (legato).
7. **Distortion** — optional tanh saturation after the filter.
8. **Output** — normalized, then scaled by VOLUME (no spurious re-normalization, so
   VOLUME actually does something).

The **sequencer** handles 16 steps, subdivisions (SCALE), swing (SHUFFLE), play modes
(PLAY MODE), and repetition (`repeats`).

---

## Pattern notation

A pattern is a list of strings, one per step:

| Spelling | Meaning |
|---|---|
| `"C2"` | note (C, octave 2) |
| `"C#2"` / `"D#2"` … | sharps |
| `"C2+"` | **accented** note |
| `"C2~"` | note with **slide** (into the next) |
| `"."` | rest (silence) |

Keyboard octaves: 1, 2, 3. Example (the demo pattern):

```python
["C2", "C2~", "C3", "C2+", "D#2", "C2~", "C3", "A#1",
 "C2", "G2~", "C3+", "C2", "D#2", "C2", "A#1~", "C2+"]
```

---

## Using the engine as a library

`tb303.py` can be used on its own, with no interface:

```python
from tb303 import TB303, DEMO_PATTERN

tb = TB303(sample_rate=44100)

audio = tb.render(
    DEMO_PATTERN,        # list of steps (see notation)
    bpm=130,
    waveform="saw",      # "saw" or "square"
    cutoff=0.32,         # 0..1
    resonance=0.85,      # 0..1
    env_mod=0.6,         # 0..1
    decay=0.5,           # 0..1
    accent=0.6,          # 0..1
    distortion=0.2,      # 0..1
    tuning=440.0,        # Hz (A reference)
    gate_len=0.55,       # note length (0..1)
    repeats=4,           # number of loops
    subdiv=4,            # 2,3,4,6,8 (see SCALE)
    swing=0.15,          # 0..0.66
    play_mode="forward", # forward/reverse/fwd_rev/invert/random
)

tb.write_wav(audio, "out.wav")   # stereo 16-bit 44.1 kHz
```

Running the engine directly generates a demo file:

```bash
python3 tb303.py        # -> tb303_demo.wav
```

> **Note on `write_wav`**: by default it **respects the level** of the supplied signal
> (no auto-normalization), so the VOLUME knob has an effect. If you want it to
> normalize, call `tb.write_wav(audio, "x.wav", normalize=True)`.

Exposed helpers: `note_to_freq(name, tuning)`, `parse_step(s)`,
`apply_play_mode(steps, mode)`, and the `DEMO_PATTERN` constant.

---

## The skin system (image + coordinate map)

The interface doesn't draw its controls: it **displays an image** (`tb303_skin.png`)
and **overlays functional controls** at precise coordinates (knob needles, value text,
menus, clickable buttons, live notes on the cells).

These coordinates live in the **`SKIN_MAP`** dictionary at the top of
`tb303_studio.py` (in native image pixels). For each knob: center, radius, value-text
position; for buttons/cells: center + half-width/half-height; for the keyboard and the
strip: their bounding rectangle.

The image is shown at native size, or scaled down automatically to fit the screen; the
coordinates are scaled accordingly, so alignment stays correct at any screen size.

---

## Creating a new skin

To skin the synth with a **different image** (a cyberpunk, a classic…), you must give
the program the control positions. The reliable method:

1. Start from a panel image (same general layout: knobs on top, keyboard, 16-step
   strip, etc.).
2. On **a copy**, in an editor (GIMP, Photopea…), mark in **bright red (#FF0000)**:
   - a **circle** at the center of each knob (10),
   - a **rectangle** around each control (buttons, menus, banks, value fields), one big
     rectangle around the **keyboard**, and one around the **16-cell strip**.
3. Those red marks are detected automatically by image analysis: the exact coordinates
   are extracted, the **red is erased** (and the cells/values blanked) to produce the
   clean skin, and the `SKIN_MAP` is filled in.

> Tip: mark on a **copy of the final image** — don't regenerate the image with the
> marks (it would shift the layout and the coordinates wouldn't match anymore).

This is exactly the procedure used to build `tb303_skin.png` and its current map.

---

## Troubleshooting

**RUN / STOP do nothing.** The button does fire, but it has nothing to play if the audio
engine isn't active. Click RUN: a dialog will explain why. Usually **pygame** is missing
→ `python3 -m pip install pygame`, then relaunch. (SAVE WAV works without pygame.)

**No sound even though the status says "Pret".** Check the system volume and, on WSL,
that you're launching from WSL (not a shell where stale PulseAudio variables linger).
WSLg routing is automatic when `/mnt/wslg/PulseServer` exists.

**Window won't open / ImageTk error.** On Ubuntu, install `python3-pil.imagetk` (and
`python3-tk`). `ImageTk` doesn't always ship with Pillow alone.

**pip refuses ("externally-managed-environment").** Recent Ubuntu. Use apt
(`sudo apt install python3-…`), a virtualenv, or `pip install --break-system-packages`.

**Controls land off the image.** If you use an image **different** from `tb303_skin.png`
without adapting `SKIN_MAP`, the coordinates won't match. Redo the "Creating a new skin"
procedure.

**Sound is saturated / too loud.** Lower VOLUME, and don't stack DIST + RESONANCE at max
at the same time: each adds energy.

---

## File-by-file notes

**`tb303.py`** — engine with no GUI dependency. `TB303` class (`render`, `write_wav`
methods), `note_to_freq`, `parse_step`, `apply_play_mode` functions, the `DEMO_PATTERN`
constant, and a demo `main()`. Editable independently of the interface.

**`tb303_studio.py`** — skin interface. Holds `SKIN_MAP` (coordinates), the overlay
rendering, click/wheel handling, audio (pygame + automatic WSLg routing), WAV export,
keyboard note preview, and the `.tb303` project save/load (File menu, Ctrl+S / Ctrl+O).
Imports `tb303.py`.

**`tb303_skin.png`** — skin image 1817×866, with the cells and value fields already
blanked, ready to receive the overlays.

---

*Character emulation for personal/educational use. Original panel design; no Roland
branding, logo, or sample is used.*
