# TB-303 Studio — Complete Live Lights Edition

This archive is a **complete project**, not a patch. Extract its contents into an
empty TB303-Studio directory, or copy its contents into an existing checkout after
backing up files you have modified. The ZIP has no intermediate `files/` directory.

## Start

```bash
python3 -m pip install numpy pillow numba sounddevice mido python-rtmidi scipy soundfile pygame
python3 Python_Scripts/tb303_studio.py
```

On Debian/Ubuntu, you may also need `python3-tk`, `libportaudio2`, and `ffmpeg`.
See the original `README.md` for the detailed installation instructions.

## This edition includes

- All original Python scripts and assets from the supplied TB303-Studio V1 project
- Original Steampunk skin (`docs/tb303_skin.png`), selected by default
- Ten additional art skins in **`doc/skin/`**, selectable from **Skin**
- Sound-reactive decoration and VU-style lights (`skin_lighting.py`)
- The **Record / Stop Rec** button for real-time audio capture (`live_recording.py`)
- The separate offline audio export from the **File** menu
- Sample instruments, projects, music, and the audio-to-pattern converter

The main entry point is `Python_Scripts/tb303_studio.py`. The optional MIDI
controller can be skipped with `--nomidi`. A startup launcher can be installed with
`python3 Python_Scripts/install_launcher.py` after placing the project in its final
location.

## Folder layout

```text
Python_Scripts/  application and supporting modules
Instruments/     bundled instrument samples
Projects/        example .tb303 projects
Musics/          bundled audio examples
docs/            original panel, icon and documentation images
doc/skin/        ten additional themed skin images
```

Do not confuse `docs/` (original assets) with `doc/skin/` (new skins). Both
are required for this complete distribution.

The ZIP intentionally omits the original `.git` history, old Python caches and
session log files. No user preferences or example project files are deleted.
