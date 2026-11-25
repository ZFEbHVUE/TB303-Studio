# TB-303 Studio — Classic · Front Panel Mk III.2

Extract the **TB303-Studio-MkIII.2** folder, then open a terminal in that folder.
It contains the entire Studio and its own launcher. The original project files and samples can remain in your previous installation. The window title says **Front Panel Mk III.2**. BACK and REDO are fitted below the keyboard, next to the cursor keys. While RUN is playing a pattern, a pad or pattern button queues its replacement at the next loop boundary.

The menus, file chooser, confirmations, sequencer display and all eleven instruments now use English. The factory samples have English filenames; older projects can still load their original names. See [the menu in the running Studio](docs/Sequencer_Menu.png).

## Start

```bash
python3 -m pip install numpy pillow numba sounddevice mido python-rtmidi scipy soundfile pygame
python3 Launch_TB303_MkIII.py
```

On Debian/Ubuntu, you may also need `python3-tk`, `libportaudio2`, and `ffmpeg`.
See the original `README.md` for the detailed installation instructions.

For the new photographic instrument choose **Panel → Roland TB-303 (photo)** or run `python3 Launch_Roland_TB303.py`. The default launcher and all eleven existing skins still work. See the [photo panel guide](ROLAND-PANEL.md) and [animation](docs/Roland-TB303-Panel-Demo.gif).

## This edition includes

- 24 controls in two parts of each chassis. Each factory face uses its own RUN/STOP rockers, articulation key castings, metal finishes and illustrated material. The original sixteen step keys sit between the new controls. [Compare the eleven running instruments](docs/Inlaid_Skins_MkIII.jpg).
- SCALE, PLAY MODE and PRESET open directly on the instrument, using its own metal finish and lettering. A mouse selection closes the list without an underline. [See the open selectors](docs/TB303-MkIII.1-Selectors.png). The rotating dial index leaves the original hub exposed. See [the illustrated guide](CLASSIC-GUIDE.md) for mouse and keyboard operation.
- The original synth, MIDI, recording and import functions, including the optional v1.0 launcher
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
doc/skin/        ten additional themed bases, eleven inlays and editable art sources
```

Do not confuse `docs/` (original assets) with `doc/skin/` (new skins). Both
are required for this complete distribution.

The ZIP intentionally omits the original `.git` history, old Python caches and
session log files. No user preferences or example project files are deleted.

## Language convention

Use English for menu labels, dialog text, the sequencer display, console messages, Python identifiers, comments and docstrings. Keep user filenames and project data as supplied.
