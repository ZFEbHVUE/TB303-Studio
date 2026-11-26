#!/usr/bin/env python3
"""Entry point of the stand-alone executables (TB303-Studio.spec, built for
Linux and Windows by .github/workflows/executables.yml).

    TB303-Studio                      the studio
    TB303-Studio --import-audio ...   the audio import, with audio_to_tb303.py's
                                      options: the studio starts it as a second
                                      process, and an executable has no Python
                                      to run the script with
    TB303-Studio --self-test          checks a build without a sound card, then
                                      exits (0 = passed); --no-gui skips the window

Run from the sources (python Python_Scripts/standalone_main.py --self-test), it
checks the installed Python the same way.
"""
import os
import sys
import time

FROZEN = getattr(sys, "frozen", False)
APP_DIR = (os.path.dirname(os.path.abspath(sys.executable)) if FROZEN
           else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if not FROZEN:
    sys.path.insert(0, os.path.join(APP_DIR, "Python_Scripts"))


def _portaudio_fallback():
    """sounddevice uses the system's PortAudio. The Linux executable carries a
    copy for machines that do not have it (no libportaudio2 package)."""
    if not (FROZEN and sys.platform.startswith("linux")):
        return
    import ctypes.util
    bundled = os.path.join(getattr(sys, "_MEIPASS", APP_DIR), "libportaudio.so.2")
    if not os.path.isfile(bundled):
        return
    find = ctypes.util.find_library

    def find_library(name):
        found = find(name)
        return bundled if found is None and name == "portaudio" else found
    ctypes.util.find_library = find_library


def _import_voices():
    """Numba keeps the compiled voices in the user's cache folder, under a name
    made from the current folder when a frozen module is first imported. Import
    them from the program's folder, so that every launch finds the same cache
    and only the first one compiles."""
    try:
        here = os.getcwd()
        os.chdir(APP_DIR)
    except OSError:
        here = None
    try:
        import classic_voice, tb303_rt, instruments_rt  # noqa: F401,E401
    finally:
        if here is not None:
            try:
                os.chdir(here)
            except OSError:
                pass


def _utf8_lines(stream):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except (AttributeError, ValueError):
        pass


def run_import(argv):
    """audio_to_tb303.py inside the executable: same options, same output."""
    for stream in (sys.stdout, sys.stderr):
        _utf8_lines(stream)
    sys.argv = [sys.argv[0]] + argv
    _import_voices()
    import audio_to_tb303
    audio_to_tb303.main()


def import_command(path, output, *options):
    """The command the studio uses for an import (see tb303_studio._import_audio)."""
    if FROZEN:
        return [sys.executable, "--import-audio", path, "-o", output, *options]
    script = os.path.join(APP_DIR, "Python_Scripts", "audio_to_tb303.py")
    return [sys.executable, "-u", script, path, "-o", output, *options]


# ---------------------------------------------------------------------------
# --self-test

TEST_NOTES = [36, 36, 48, 39, -1, 36, 43, 36, 41, 36, 48, -1, 36, 43, 39, 36]
TEST_SLIDES = [False, True] + [False] * 14


def _numerics():
    import numpy, scipy, numba, llvmlite, PIL                           # noqa: E401
    return (f"numpy {numpy.__version__}, scipy {scipy.__version__}, numba {numba.__version__}"
            f" (llvmlite {llvmlite.__version__}), Pillow {PIL.__version__}")


def _pygame():
    import pygame
    return f"pygame {pygame.version.ver} (SDL {'.'.join(map(str, pygame.get_sdl_version()))})"


def _soundfile():
    import soundfile
    return f"soundfile {soundfile.__version__} (libsndfile {soundfile.__libsndfile_version__})"


def _sounddevice():
    import sounddevice
    return f"sounddevice {sounddevice.__version__} ({sounddevice.get_portaudio_version()[1]})"


def _tk():
    import tkinter
    return f"Tk {tkinter.TkVersion}"


def _midi():
    import mido, rtmidi                                                  # noqa: E401,F401
    import mido.backends.rtmidi                                          # noqa: F401
    return f"mido with RtMidi {rtmidi.get_rtmidi_version()}"


def _check_libraries(say):
    missing = []
    for probe in (_numerics, _pygame, _soundfile, _sounddevice, _tk, _midi):
        try:
            say(probe())
        except Exception as e:                    # report each one, then fail once
            missing.append(f"{probe.__name__[1:]}: {type(e).__name__}: {e}")
    if missing:
        raise ImportError("; ".join(missing))


def _check_folders(say):
    import tb303_studio
    skin = tb303_studio._find_skin()
    for label, path in (("skin", skin), ("icon", tb303_studio.ICON_PATH),
                        ("Projects", tb303_studio.PROJECTS_DIR),
                        ("Instruments", tb303_studio.INSTRUMENTS_DIR)):
        if not os.path.exists(path):
            raise FileNotFoundError(f"{label} not found: {path}")
    say(f"folders found in {tb303_studio.ROOT}")


def _check_voices(say):
    import numpy as np
    import tb303_rt, instruments_rt                                      # noqa: E401
    t = time.time()
    tb303_rt.warm_up()
    instruments_rt.warm_up()
    say(f"voices ready in {time.time() - t:.1f} s (compiled once, then read from the cache)")
    for profile in ("legacy", "classic"):
        e = tb303_rt.RealtimeEngine()
        e.set_profile(profile)
        e.set_pattern(["C2", "C3+", "G2~", "D#2"] * 4)
        e.set_playing(True)
        out = np.empty(8192)
        e.process(out)
        if not (np.isfinite(out).all() and np.abs(out).max() > 1e-4):
            raise RuntimeError(f"the {profile} voice is silent or not finite")
    say("TB-303 voice plays")


def _check_import(say, folder):
    """Plays a known line with the studio's engine, imports it the way the studio
    does (a second process), and compares the notes."""
    import json, subprocess, wave                                        # noqa: E401
    import numpy as np
    import audio_to_tb303 as fit
    import tb303_rt
    grid = fit.Grid(bpm=120, start=0, subdiv=4, shuffle=0.)
    notes = np.array(TEST_NOTES)
    accents = notes == 39
    timbre = (.3, .81, .52, .68, .82, 0., .8)
    frames = int(fit.SR * 6 * grid.duration)
    audio = fit.play(fit.fitting_engine(tb303_rt, "legacy"), grid, 440, notes,
                     np.array(TEST_SLIDES), accents, timbre, "saw", frames)
    pcm = (np.clip(audio / max(1e-9, np.abs(audio).max()) * 0.7, -1, 1) * 32767).astype("<i2")
    wav = os.path.join(folder, "self_test_line.wav")
    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fit.SR)
        w.writeframes(pcm.tobytes())
    out = os.path.join(folder, "self_test_line.tb303")
    t = time.time()
    proc = subprocess.run(import_command(wav, out, "--scale", "1/16", "--profile", "legacy"),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=900,
                          encoding="utf-8", errors="replace", cwd=APP_DIR,
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if proc.returncode != 0 or not os.path.isfile(out):
        raise RuntimeError(f"the import failed (exit {proc.returncode}): " + " | ".join(lines[-6:]))
    if not any(line.startswith("Pattern: ") for line in lines):
        raise RuntimeError("the import printed no 'Pattern:' line: " + " | ".join(lines[-6:]))
    with open(out, encoding="utf-8") as f:
        got = [step["note"] for step in json.load(f)["banks"][0]]
    want = [fit.note_name(n) if n >= 0 else None for n in TEST_NOTES]
    right = sum(a == b for a, b in zip(got, want))
    say(f"import through {'the program' if FROZEN else 'Python'} in {time.time() - t:.0f} s: "
        f"{right}/16 notes right ({' '.join(n or '-' for n in got)})")
    if right < 14:
        raise RuntimeError(f"only {right} of 16 notes read back")


def _check_window(say):
    import tkinter as tk
    import studio_messages
    import tb303_studio
    shown = []
    for name in ("showinfo", "showwarning", "showerror", "askyesno", "askyesnocancel", "askstring"):
        setattr(studio_messages, name, lambda title, message, *a, _n=name, **k:
                shown.append(f"{_n}: {title}: {message}"))
    errors = []
    root = tk.Tk(className=tb303_studio.WM_CLASS)
    root.report_callback_exception = lambda kind, exc, tb: errors.append(repr(exc))
    app = tb303_studio.SkinStudio(root, tb303_studio._find_skin())
    for _ in range(20):
        root.update()
        time.sleep(0.05)
    app.close()
    root.destroy()
    if errors or shown:
        raise RuntimeError("; ".join(errors + shown))
    say("window opens and closes")


def self_test(gui=True):
    import tempfile
    import traceback
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")      # build machines have no sound card
    log_path = os.path.join(APP_DIR, "self_test.log")
    lines = []
    for stream in (sys.stdout, sys.stderr):
        _utf8_lines(stream)

    def say(text):
        lines.append(text)
        if sys.stdout is not None:
            print(text, flush=True)

    say(f"TB-303 Studio self-test, {'executable' if FROZEN else 'sources'}: {sys.executable}")
    checks = [("libraries", _check_libraries),
              ("voice modules", lambda say: _import_voices()),     # before the studio imports them
              ("folders", _check_folders), ("voices", _check_voices)]
    folder = tempfile.mkdtemp(prefix="tb303_selftest_")
    checks.append(("import", lambda say: _check_import(say, folder)))
    if gui:
        checks.append(("window", _check_window))
    failed = []
    on_github = os.environ.get("GITHUB_ACTIONS") == "true"
    for name, check in checks:
        try:
            check(say)
        except Exception as e:
            failed.append(name)
            say(f"FAILED {name}: {type(e).__name__}: {e}")
            for line in traceback.format_exc().splitlines():
                say("    " + line)
            if on_github:      # shown in the Annotations box of the run's page
                text = f"{type(e).__name__}: {e}".replace("%", "%25").replace("\r", "").replace("\n", "%0A")
                say(f"::error title=Self-test {name} ({sys.platform})::{text}")
    say("SELF-TEST " + ("PASSED" if not failed else "FAILED: " + ", ".join(failed)))
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass
    return 0 if not failed else 1


def main():
    _portaudio_fallback()
    args = sys.argv[1:]
    if args[:1] == ["--import-audio"]:
        run_import(args[1:])
    elif "--self-test" in args:
        try:
            code = self_test(gui="--no-gui" not in args)
        except Exception:                 # an error dialog would hide it on a build machine
            import traceback
            traceback.print_exc(file=sys.stdout if sys.stdout is not None else None)
            code = 2
        sys.exit(code)
    else:
        _import_voices()
        import tb303_studio
        tb303_studio.main()


if __name__ == "__main__":
    main()
