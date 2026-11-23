#!/usr/bin/env python3
"""
tb303_studio.py - skinned GUI: the panel is an image (tb303_skin.png), with
functional controls overlaid at coordinates taken from the red markers.

Lives in Python_Scripts/ with tb303.py and the other modules. The Art Controls
skins are in doc/skin/. Requires numpy and Pillow. Pygame is optional, as is
tb303_rt for real-time playback. Run python Python_Scripts/tb303_studio.py or
use the desktop icon made by Python_Scripts/install_launcher.py.
"""
import sys, os, json, math, time, shutil, filecmp, subprocess, tempfile, threading, queue
import numpy as np
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox
from tb303 import TB303, DEMO_PATTERN, parse_step, apply_play_mode
from live_recording import MixerOutputTap, WaveTake
from skin_lighting import STYLES, SkinLights
import instruments
import instruments_rt
try:
    from tb303_rt import RealtimeEngine, _HAS_NUMBA
    _HAS_RT = _HAS_NUMBA          # real-time only if Numba is present (else too slow)
except Exception:
    _HAS_RT = False
try:
    from PIL import Image, ImageTk
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False
try:
    import pygame
    _HAS_PYGAME = True
except Exception:
    _HAS_PYGAME = False
# File chooser: the Tk/ttk chooser shared with XTTS Studio (sizes, dates,
# sorting, search, favourites, and Listen on audio files). It replaces Tk's
# basic dialogs everywhere in this program; without the module they stay.
try:
    import studio_file_dialog as _file_dialog
    filedialog.askopenfilename = _file_dialog.askopenfilename
    filedialog.askopenfilenames = _file_dialog.askopenfilenames
    filedialog.asksaveasfilename = _file_dialog.asksaveasfilename
    filedialog.askdirectory = _file_dialog.askdirectory
except Exception:
    _file_dialog = None

SCALE_MAP = {"1/8": 2, "1/8T": 3, "1/16": 4, "1/16T": 6, "1/32": 8}
PLAYMODES = {"Forward": "forward", "Reverse": "reverse", "Fwd&Rev": "fwd_rev",
             "Invert": "invert", "Random": "random"}
PRESETS = {
    "Classic Bass": {"waveform": "square", "cutoff": 0.40, "resonance": 0.10,
                     "env_mod": 0.12, "decay": 0.40, "accent": 0.30, "distortion": 0.0, "shuffle": 0.0},
    "Acid":         {"waveform": "saw", "cutoff": 0.30, "resonance": 0.84,
                     "env_mod": 0.65, "decay": 0.55, "accent": 0.70, "distortion": 0.28, "shuffle": 0.0},
    "Sub Bass":     {"waveform": "square", "cutoff": 0.24, "resonance": 0.06,
                     "env_mod": 0.06, "decay": 0.55, "accent": 0.30, "distortion": 0.0, "shuffle": 0.0},
    "Rubber":       {"waveform": "saw", "cutoff": 0.36, "resonance": 0.45,
                     "env_mod": 0.35, "decay": 0.45, "accent": 0.45, "distortion": 0.0, "shuffle": 0.0},
}
KNOB_SPEC = {
    "tuning": (400, 480, 440, "{:.0f}"), "cutoff": (0, 1, 0.40, "{:.2f}"),
    "resonance": (0, 1, 0.10, "{:.2f}"), "env_mod": (0, 1, 0.12, "{:.2f}"),
    "decay": (0, 1, 0.40, "{:.2f}"), "accent": (0, 1, 0.30, "{:.2f}"),
    "bpm": (60, 200, 130, "{:.0f}"), "distortion": (0, 1, 0.0, "{:.2f}"),
    "volume": (0, 1, 0.9, "{:.2f}"), "shuffle": (0, 0.66, 0.0, "{:.2f}"),
}

# Coordinate map (native image pixels) taken from the red markers
SKIN_MAP = {
    "knobs": {
        "tuning": [277, 105, 44, 280, 191], "cutoff": [386, 105, 44, 386, 190],
        "resonance": [496, 104, 44, 495, 191], "env_mod": [605, 105, 44, 604, 190],
        "decay": [713, 104, 44, 713, 190], "accent": [814, 105, 44, 814, 189],
        "bpm": [131, 264, 40, 134, 344], "distortion": [237, 263, 40, 238, 344],
        "volume": [340, 264, 40, 340, 343], "shuffle": [443, 265, 40, 446, 343],
    },
    "waveform": {"saw": [93, 108], "square": [93, 151]},
    "combos": {"scale": [599, 312, 109], "playmode": [738, 313, 141], "preset": [910, 314, 178]},
    "banks": [1086, 1162, 1238, 1314, 1390, 1466, 1542, 1618], "banks_y": 321,
    "buttons": {
        "run": [148, 437, 55, 33], "stop": [149, 542, 54, 31],
        "accent": [1074, 461, 44, 16], "slide": [1234, 461, 37, 15],
        "oct_down": [1379, 461, 35, 14], "oct_up": [1512, 462, 36, 14], "rest": [1646, 461, 32, 14],
        "record": [455, 728, 63, 16], "clear": [629, 729, 46, 17], "demo": [783, 728, 43, 17],
    },
    "piano": [259, 394, 986, 545],
    "cells": {"cx": [401, 474, 548, 622, 696, 769, 843, 917, 993, 1068, 1142, 1217,
                     1292, 1367, 1447, 1525], "cy": 602, "hw": 32, "hh": 28},
    "status": [880, 728], "status_right": 1325,   # the bottom bar's dark panel ends at x 1340
    "show_values": True,
    "ink": "#241a0a", "needle": "#ffcf6b", "accent_fg": "#c0451f", "slide_fg": "#3f7fa0",
    "val_fg": "#f0d9a0", "sel": "#ffcf6b", "status_fg": "#d8c08a",
    "font": "Georgia", "knob_hub": "#1a1206",
    "combo_colors": ("#2a1c0e", "#5a4326", "#f0d9a0"),
    "lamps": ((33, 325, 36), (1291, 96, 26), (1691, 212, 24)),
    "lamp_color": (255, 190, 90),
}

# The bundled skins share the same native coordinate map and hit targets.
PANEL_SIZE = (1817, 866)
DEFAULT_SKIN = "steampunk"
# Each palette supplies readable colours for the Tk overlays on its PNG.
# label, screen ink, dial needle, accent marker, slide marker, field, button, lamp
ART_SKINS = {
    "cyberpunk": ("Cyberpunk", "#e4f9ff", "#5cf5ff", "#ff8cc5", "#81edff",
                  "#102133", "#344969", (104, 229, 255)),
    "hard_cyberpunk": ("Hard Cyberpunk", "#f3efe4", "#ff9b43", "#ffac73", "#f3db78",
                       "#191e26", "#474443", (255, 150, 65)),
    "cyber_reggae": ("Cyber-Reggae", "#e3fbda", "#6ffa8b", "#ffc361", "#a1ffcc",
                     "#0a281f", "#355a37", (138, 255, 112)),
    "goa_trance": ("Goa Trance", "#f5eaff", "#6ef5e6", "#ffa4e0", "#9dfff5",
                   "#241637", "#5a386e", (144, 101, 255)),
    "trance_dub": ("Trance Dub", "#e2f7ff", "#65dfff", "#ffc1ff", "#a3dcff",
                   "#121b39", "#314d76", (100, 189, 255)),
    "dub": ("Dub", "#fff1d3", "#ffc16a", "#ffab83", "#d4e7ad",
            "#241d15", "#584631", (255, 171, 72)),
    "reggae": ("Reggae", "#ffefc5", "#ffd24d", "#ffb2a1", "#a9ffae",
               "#182c1d", "#554831", (255, 185, 73)),
    "steampunk_ii": ("Steampunk II", "#eefaf0", "#efc66f", "#ffb395", "#99e9d1",
                     "#112722", "#475a43", (255, 187, 82)),
    "classic": ("TB-303 Classic", "#182128", "#ff654f", "#a72221", "#175774",
                "#ecede8", "#abb1b0", (255, 96, 66)),
    "acid_rave": ("Acid Rave", "#f3f4de", "#d5fb43", "#efa9ff", "#aaffaf",
                  "#171c1b", "#43423c", (208, 248, 70)),
}


def _art_skin_style(key, ink, needle, accent, slide, field, button, lamp):
    classic = key == "classic"
    return {
        "ink": ink, "needle": needle, "accent_fg": accent, "slide_fg": slide,
        "val_fg": ink, "sel": "#b62d29" if classic else needle,
        "status_fg": "#e0e8e9" if classic else ink,
        "font": "DejaVu Sans" if classic else "DejaVu Sans Mono",
        "knob_hub": "#25282a" if classic else field,
        "combo_colors": (field, button, ink),
        "lamps": ((1441, 108, 13), (1495, 108, 13), (1549, 108, 13)),
        "lamp_color": lamp,
    }


SKINS = {
    DEFAULT_SKIN: ("Steampunk", "tb303_skin.png", {}),
    **{key: (label, f"tb303_skin_{key}.png", _art_skin_style(key, *palette))
       for key, (label, *palette) in ART_SKINS.items()},
}

# Projects and the samples they use live in two folders next to this script.
# A loaded sample is COPIED into Instruments/, and a project refers to it by
# file name, so the whole TB303-Studio folder can be moved or shared as is.
#
# Layout:  TB303-Studio/
#            Python_Scripts/   this script and the other modules
#            Projects/         .tb303 projects
#            Instruments/      samples used by the projects
#            doc/skin/         Art Controls skins
# The script also still runs from the old flat layout (everything in one folder).
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE) if os.path.basename(HERE) == "Python_Scripts" else HERE
PROJECTS_DIR = os.path.join(ROOT, "Projects")
INSTRUMENTS_DIR = os.path.join(ROOT, "Instruments")
DOC_DIR = os.path.join(ROOT, "doc")
ART_SKINS_DIR = os.path.join(DOC_DIR, "skin")
# Tk turns the class name into WM_CLASS ("tb303-studio", "Tb303-studio"); GNOME
# matches the first part to the launcher (StartupWMClass, tb303-studio.desktop).
# Keep it lowercase: Tk would otherwise rewrite it ("TB303Studio" -> "tB303Studio").
WM_CLASS = "tb303-studio"


def _find_asset(filename):
    # The original panel and icon can be in the current or legacy layout.
    for folder in (ART_SKINS_DIR, DOC_DIR, os.path.join(ROOT, "docs"), HERE, ROOT):
        path = os.path.join(folder, filename)
        if os.path.isfile(path):
            return path
    return os.path.join(ART_SKINS_DIR, filename)


def _find_skin():
    return _find_asset(SKINS[DEFAULT_SKIN][1])


ICON_PATH = _find_asset("tb303_icon.png")


def _migrate_lowercase_folders():
    """projects/ and instruments/ became Projects/ and Instruments/: move the
    old folders' content over, once, never overwriting anything."""
    for old_name, new in (("projects", PROJECTS_DIR), ("instruments", INSTRUMENTS_DIR)):
        old = os.path.join(ROOT, old_name)
        if not os.path.isdir(old) or os.path.normcase(old) == os.path.normcase(new):
            continue
        try:
            if os.path.exists(new) and os.path.samefile(old, new):
                continue                     # case-insensitive disk: same folder
            if not os.path.exists(new):
                os.rename(old, new)
                continue
            for name in os.listdir(old):
                src, dst = os.path.join(old, name), os.path.join(new, name)
                if not os.path.exists(dst):
                    shutil.move(src, dst)
            if not os.listdir(old):
                os.rmdir(old)
        except OSError as e:
            print(f"Could not move {old} to {new}: {e}")
TB303_ID = "TB-303"
SAMPLE_PREFIX = "Sample: "              # instrument id of a sample = prefix + file name
N_BANKS = 8
PROJECT_VERSION = 3


def fit_text(text, font, width):
    """text cut with an ellipsis so that it is at most width pixels wide in font."""
    if width <= 0:
        return ""
    if font.measure(text) <= width:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.measure(text[:mid].rstrip() + "\u2026") <= width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + "\u2026" if lo else ""


class SkinStudio:
    SR = 44100

    def __init__(self, root, image_path):
        if not _HAS_PIL:
            raise SystemExit("Pillow requis : pip install pillow")
        self.root = root
        self.tb = TB303(self.SR)
        self._skins = {
            key: (label, _find_skin() if key == DEFAULT_SKIN else os.path.join(ART_SKINS_DIR, filename), style)
            for key, (label, filename, style) in SKINS.items()
        }
        requested_path = os.path.realpath(image_path)
        self._skin = next((key for key, (_, path, _) in self._skins.items()
                           if os.path.realpath(path) == requested_path), "custom")
        if self._skin == "custom":
            self._skins["custom"] = ("Custom: " + os.path.basename(image_path), image_path, {})
        self.skin_v = tk.StringVar(root, value=self._skin)
        self.M = {**SKIN_MAP, **self._skins[self._skin][2]}
        self.img, self.scale, self._disp_rgb, self.bg = self._prepare_panel(image_path, self._skin)
        self.IW, self.IH = self.img.size
        self._update_window_title()
        root.resizable(False, False)
        self.cv = tk.Canvas(root, width=self._disp_rgb.width, height=self._disp_rgb.height,
                            highlightthickness=0)
        self.cv.pack()
        self._background_item = self.cv.create_image(0, 0, anchor="nw", image=self.bg)

        self.kv = {k: KNOB_SPEC[k][2] for k in KNOB_SPEC}
        self.waveform = "square"
        self.scale_v = tk.StringVar(value="1/16")
        self.playmode_v = tk.StringVar(value="Forward")
        self.preset_v = tk.StringVar(value="Classic Bass")
        self.steps = []
        self._load_pattern(DEMO_PATTERN)
        self.banks = [None] * N_BANKS
        self.bank_settings = [None] * N_BANKS    # per-bank knob/waveform/scale/mode snapshot
        self.bank_instr = [TB303_ID] * N_BANKS   # per-bank instrument id
        self.banks[0] = [dict(s) for s in self.steps]
        self.cur_bank = 0
        self.sel = 0
        self.playing = False
        self._drag = None
        # The lamps in each skin act as VU indicators.
        self.level = 0.0
        self._vu_on = False
        self._vu_job = None
        self._audition_until = 0.0
        self._audition_note = None
        self._lighting = None
        self._lamp_items = []
        self._lamp_frames = []
        self._loop_audio = None
        self._loop_t0 = 0.0
        self._loop_dur = 1.0
        self._take = None
        self._record_engine = None
        self._mixer_tap = None
        self._mixer_error = None
        self._mixer_take = None
        self._mixer_level = 0.0
        self._build_lamp_frames()
        self.audio_ok = self._init_audio()
        self._presample_colors()
        self._make_combos()
        self.cv.bind("<Button-1>", self._click)
        self.cv.bind("<B1-Motion>", self._motion)
        self.cv.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag", None))
        self.cv.bind("<MouseWheel>", self._wheel)
        self.cv.bind("<Button-4>", self._wheel)
        self.cv.bind("<Button-5>", self._wheel)
        # --- File menu: .tb303 project (full state) + WAV export ---
        menubar = tk.Menu(root)
        filem = tk.Menu(menubar, tearoff=0)
        filem.add_command(label="Open project\u2026   (Ctrl+O)", command=self._load_project)
        filem.add_command(label="Save project\u2026   (Ctrl+S)", command=self._save_project)
        filem.add_separator()
        filem.add_command(label="Import pattern from audio\u2026", command=self._import_audio)
        filem.add_command(label="Export WAV\u2026", command=self._save)
        menubar.add_cascade(label="File", menu=filem)
        # Rebuilt each time it opens, so a file dropped into Instruments/ shows up.
        self.instr_menu = tk.Menu(menubar, tearoff=0,
                                  postcommand=lambda: self._rebuild_instr_menu())
        self.instrument = TB303_ID
        self.voice = None
        self.samples = {}                        # id -> {"name", "path", "sampler"}
        self.irt = None
        self.irt_ok = instruments_rt._HAS_RT_INSTR
        if self.irt_ok:                          # compile the sampler now, not on first use
            threading.Thread(target=instruments_rt.warm_up, name="sampler warm-up",
                             daemon=True).start()
        self._one_stream = False                 # True when the device takes one stream only
        self._instr_rt = False
        self._instr_var = tk.StringVar(value=TB303_ID)
        self._rebuild_instr_menu()
        menubar.add_cascade(label="Instrument", menu=self.instr_menu)
        skin_menu = tk.Menu(menubar, tearoff=0)
        for key, (label, _, _) in self._skins.items():
            skin_menu.add_radiobutton(label=label, variable=self.skin_v, value=key,
                                      command=self._change_skin)
        skin_menu.add_separator()
        skin_menu.add_command(label="Active Skin Details…", command=self._show_skin_details)
        menubar.add_cascade(label="Skin", menu=skin_menu)
        _migrate_lowercase_folders()
        for d in (PROJECTS_DIR, INSTRUMENTS_DIR):
            try:
                os.makedirs(d, exist_ok=True)
            except OSError:
                pass
        if _file_dialog is not None:
            _file_dialog.configure(
                parent=lambda: self.root,
                shortcuts=lambda: [("Projets TB-303", PROJECTS_DIR),
                                   ("Instruments", INSTRUMENTS_DIR),
                                   ("TB303-Studio", ROOT)],
                app_name="tb303_studio")          # its own favourites and last folders
        root.config(menu=menubar)
        root.bind("<Control-s>", lambda e: self._save_project())
        root.bind("<Control-o>", lambda e: self._load_project())
        self._apply_preset("Classic Bass")
        self.refresh()

    def _prepare_panel(self, path, skin):
        with Image.open(path) as source:
            image = source.convert("RGB")
        if skin in ART_SKINS and image.size != PANEL_SIZE:
            raise ValueError(f"Expected a {PANEL_SIZE[0]} × {PANEL_SIZE[1]} px panel.")
        width, height = image.size
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        scale = min(1.0, (sw - 30) / width, (sh - 90) / height)
        display = image.copy()
        self._blank_record_plate(display, skin)
        if scale < 1:
            display = display.resize((int(width * scale), int(height * scale)), Image.LANCZOS)
        return image, scale, display, ImageTk.PhotoImage(display, master=self.root)

    @staticmethod
    def _blank_record_plate(display, skin):
        """Clear the old, baked-in text while keeping the button's frame."""
        engraved = skin in (DEFAULT_SKIN, "steampunk_ii", "custom")
        if engraved:
            left, top, right, bottom = 397, 718, 514, 741
        else:
            left, top, right, bottom = 408, 720, 502, 736
        # Fade into the adjacent material so the mounted button stays visible.
        plate = np.asarray(display.crop((left, top - 1, right, bottom + 1)), dtype=np.float32)
        face = plate[1:-1]
        height, width = face.shape[:2]
        if engraved:
            vertical = np.arange(1, height + 1)[:, None, None] / (height + 1)
            clean = plate[:1] * (1 - vertical) + plate[-1:] * vertical
        else:
            edges = np.concatenate((face[:, :4], face[:, -4:]), axis=1)
            clean = np.median(edges, axis=1, keepdims=True)
        horizontal = np.arange(width)
        feather = np.minimum(horizontal, width - 1 - horizontal)[None, :, None].clip(0, 4) / 4
        pixels = face * (1 - feather) + clean * feather
        display.paste(Image.fromarray(pixels.astype(np.uint8)), (left, top))

    def _change_skin(self):
        key = self.skin_v.get()
        if key == self._skin:
            return
        label, path, style = self._skins[key]
        try:
            image, scale, display, photo = self._prepare_panel(path, key)
        except (OSError, ValueError, tk.TclError) as exc:
            self.skin_v.set(self._skin)
            messagebox.showerror("TB-303 Studio", f"Could not load {label}:\n{path}\n\n{exc}",
                                 parent=self.root)
            return

        self._skin = key
        self.M = {**SKIN_MAP, **style}
        self.img, self.scale, self._disp_rgb, self.bg = image, scale, display, photo
        self.IW, self.IH = image.size
        self.cv.configure(width=display.width, height=display.height)
        self.cv.itemconfigure(self._background_item, image=self.bg)
        self._update_window_title()
        self._presample_colors()
        self._style_combos()
        self._build_lamp_frames()
        if self._vu_on:
            self._set_lamps(round(self.level * (self.NLAMPFR - 1)))
        if getattr(self, "midi", None) is not None:
            self.midi._draw_badge()
        self.refresh()

    def _update_window_title(self):
        label = self._skins[self._skin][0]
        edition = " [Live Lights]" if self._skin in STYLES else ""
        project = getattr(self, "_project_path", None)
        title = f"TB-303 Studio — {label}{edition}"
        if project:
            title += " — " + os.path.basename(project)
        self.root.title(title)

    def _show_skin_details(self):
        label, path, _ = self._skins[self._skin]
        edition = " (Live Lights)" if self._skin in STYLES else ""
        messagebox.showinfo("Active Skin", f"{label}{edition}\n\n"
                            f"Panel image\n{os.path.realpath(path)}\n\n"
                            f"Studio script\n{os.path.realpath(__file__)}",
                            parent=self.root)

    def S(self, v):
        return v * self.scale

    def _sample_hex(self, x, y, k=9):
        x0, y0 = max(0, x - k), max(0, y - k)
        patch = np.asarray(self.img.crop((x0, y0, x + k, y + k))).reshape(-1, 3)
        return "#%02x%02x%02x" % tuple(np.median(patch, axis=0).astype(int))

    def _presample_colors(self):
        self.valbg = {k: self._sample_hex(v[3], v[4], 13) for k, v in self.M["knobs"].items()}
        self.statusbg = self._sample_hex(self.M["status"][0], self.M["status"][1], 14)

    def _load_pattern(self, pattern):
        self.steps = []
        for s in pattern[:16]:
            d = parse_step(s)
            self.steps.append({"note": d["note"], "accent": d["accent"], "slide": d["slide"]})
        while len(self.steps) < 16:
            self.steps.append({"note": None, "accent": False, "slide": False})

    def _init_audio(self):
        self.audio_err = ""
        self.rt = None
        self.mode = None
        # 1) real-time engine (sounddevice + Numba) first
        if _HAS_RT:
            try:
                self.rt = RealtimeEngine(sr=self.SR)
                self.rt.start()
                self.mode = "rt"
                self._push_rt()
                return True
            except Exception as e:
                self.rt = None
                self.audio_err = f"real-time unavailable ({e}) - pygame fallback"
        # 2) fallback: old pygame engine (render + loop)
        if not _HAS_PYGAME:
            self.audio_err = self.audio_err or "pygame missing - pip install pygame"
            return False
        if os.path.exists("/mnt/wslg/PulseServer"):
            os.environ.setdefault("SDL_AUDIODRIVER", "pulseaudio")
            os.environ["PULSE_SERVER"] = "unix:/mnt/wslg/PulseServer"
        try:
            pygame.mixer.quit()
            pygame.mixer.init(frequency=self.SR, size=-16, channels=2, allowedchanges=0)
            self._install_mixer_tap()
            self.mode = "pygame"
            return True
        except Exception as e:
            self.audio_err = f"audio KO ({e})"
            return False

    def _push_rt(self, e=None):
        """Push the whole current state to the real-time engine (instant, no dropout).
        `e` is another RealtimeEngine to set up the same way (the WAV export)."""
        if e is None:
            e = self.rt
        if e is None:
            return
        for k in ("cutoff", "resonance", "env_mod", "decay", "accent", "bpm",
                  "distortion", "tuning", "volume"):
            e.set_param(k, self.kv[k])
        e.set_param("swing", self.kv["shuffle"])
        e.set_param("waveform", self.waveform)
        e.set_param("subdiv", SCALE_MAP[self.scale_v.get()])
        steps = apply_play_mode([dict(s) for s in self.steps],
                                PLAYMODES[self.playmode_v.get()])
        e.set_pattern([(s["note"], s["accent"], s["slide"]) for s in steps])

    _RT_PARAM = {"shuffle": "swing"}            # studio name -> engine name

    def _push_param(self, name):
        """Push a SINGLE parameter to the engine (negligible cost, instant response)."""
        e = self.rt
        if e is None:
            return
        if name == "waveform":
            e.set_param("waveform", self.waveform)
        elif name in self.kv:
            e.set_param(self._RT_PARAM.get(name, name), self.kv[name])

    def _push_pattern(self):
        e = self.rt
        if e is None:
            return
        steps = apply_play_mode([dict(s) for s in self.steps],
                                PLAYMODES[self.playmode_v.get()])
        e.set_pattern([(s["note"], s["accent"], s["slide"]) for s in steps])

    def _knob_live(self, k):
        """Knob moved: push audio RIGHT AWAY, redraw is coalesced."""
        if not self._is303():
            if self._instr_rt and self.irt is not None:
                self._irt_set_param(k)          # live, no re-render
            else:
                self._schedule_instr()          # coalesced re-render of the instrument loop
            self._schedule_refresh()
            return
        if self.mode == "rt" and self.rt is not None:
            try:
                self._push_param(k)             # audio first -> no latency
            except Exception:
                pass
        elif self.playing and self.audio_ok:
            self._play_loop()
        self._schedule_refresh()

    def _schedule_instr(self):
        if self.playing and not getattr(self, "_instr_pending", False):
            self._instr_pending = True
            self.root.after(55, self._do_instr)

    def _do_instr(self):
        self._instr_pending = False
        if self.playing and not self._is303():
            self._play_instr()

    def _schedule_refresh(self):
        """Coalesce redraws (~60 fps max): audio stays prioritized and immediate."""
        if not getattr(self, "_refresh_pending", False):
            self._refresh_pending = True
            self.root.after(16, self._do_refresh)

    def _do_refresh(self):
        self._refresh_pending = False
        self.refresh()

    def _make_combos(self):
        self._combos = {}
        for name, var, vals in [("scale", self.scale_v, list(SCALE_MAP)),
                                ("playmode", self.playmode_v, list(PLAYMODES)),
                                ("preset", self.preset_v, list(PRESETS))]:
            cb = ttk.Combobox(self.cv, textvariable=var, values=vals, state="readonly",
                              style="Skin.TCombobox")
            self._combos[name] = (cb, self.cv.create_window(0, 0, window=cb))
            if name == "preset":
                cb.bind("<<ComboboxSelected>>", lambda e: self._apply_preset(self.preset_v.get()))
            else:
                cb.bind("<<ComboboxSelected>>", lambda e: self._changed())
        self._style_combos()

    def _style_combos(self):
        field, button, foreground = self.M["combo_colors"]
        try:
            st = ttk.Style(self.root)
            st.theme_use("clam")
            st.configure("Skin.TCombobox", fieldbackground=field, background=button,
                         foreground=foreground, arrowcolor=foreground)
            st.map("Skin.TCombobox", fieldbackground=[("readonly", field)],
                   foreground=[("readonly", foreground)])
        except Exception:
            pass
        for name, (cb, item) in self._combos.items():
            cx, cy, w = self.M["combos"][name]
            cb.configure(width=max(6, int(self.S(w) / 8)), font=(self.M["font"], 9))
            self.cv.coords(item, self.S(cx), self.S(cy))
            self.cv.itemconfigure(item, width=round(self.S(w)) if self._skin in ART_SKINS else 0)

    def refresh(self):
        self.cv.delete("dyn")
        S = self.S
        family = self.M["font"]
        for k, (cx, cy, r, vx, vy) in self.M["knobs"].items():
            vmin, vmax, _, fmt = KNOB_SPEC[k]
            frac = (self.kv[k] - vmin) / (vmax - vmin)
            ang = math.radians(135 + frac * 270)
            self.cv.create_line(S(cx), S(cy), S(cx + (r - 6) * math.cos(ang)),
                                S(cy + (r - 6) * math.sin(ang)), fill=self.M["needle"],
                                width=max(2, int(S(3))), capstyle="round", tags="dyn")
            self.cv.create_oval(S(cx) - 3, S(cy) - 3, S(cx) + 3, S(cy) + 3,
                                fill=self.M["knob_hub"], outline=self.M["needle"], tags="dyn")
            if self.M.get("show_values"):
                self.cv.create_rectangle(S(vx) - S(22), S(vy) - S(9), S(vx) + S(22), S(vy) + S(9),
                                         fill=self.valbg[k], outline="", tags="dyn")
                self.cv.create_text(S(vx), S(vy), text=fmt.format(self.kv[k]), fill=self.M["val_fg"],
                                    font=(family, max(7, int(S(11))), "bold"), tags="dyn")
        for w, (x, y) in self.M["waveform"].items():
            if w == self.waveform:
                self.cv.create_oval(S(x) - 7, S(y) - 7, S(x) + 7, S(y) + 7,
                                    outline=self.M["needle"], width=2, tags="dyn")
        by = self.M["banks_y"]
        for i, bx in enumerate(self.M["banks"]):
            if i == self.cur_bank:
                self.cv.create_oval(S(bx) - S(22), S(by) - S(17), S(bx) + S(22), S(by) + S(17),
                                    outline=self.M["needle"], width=3, tags="dyn")
        C = self.M["cells"]
        for i, cx in enumerate(C["cx"]):
            st = self.steps[i]
            note = st["note"] or "\u00b7"
            sub = ("+" if st["accent"] else "") + ("~" if st["slide"] else "")
            col = self.M["accent_fg"] if st["accent"] else (
                self.M["slide_fg"] if st["slide"] else self.M["ink"])
            self.cv.create_text(S(cx), S(C["cy"]) - S(7), text=note, fill=col,
                                font=(family, max(8, int(S(13))), "bold"), tags="dyn")
            if sub:
                self.cv.create_text(S(cx), S(C["cy"]) + S(11), text=sub, fill=col,
                                    font=(family, max(7, int(S(10))), "bold"), tags="dyn")
            if i == self.sel:
                self.cv.create_rectangle(S(cx) - S(C["hw"]), S(C["cy"]) - S(C["hh"]),
                                         S(cx) + S(C["hw"]), S(C["cy"]) + S(C["hh"]),
                                         outline=self.M["sel"], width=3, tags="dyn")
        take = self._take
        label = "RECORD"
        ink = "#f3dbab" if self._skin in (DEFAULT_SKIN, "steampunk_ii", "custom") else self.M["ink"]
        msg = getattr(self, "_busy", None) or \
            ("\u25b6 lecture" if self.playing else (self.audio_err if not self.audio_ok else "Pret"))
        if take is not None:
            if take.recording:
                label, msg = "STOP REC", "\u25cf Recording"
                ink = "#99142a" if self._skin == "classic" else "#ff9993"
            else:
                label, msg = "SAVE TAKE", "Take ready"
        bx, by, _, _ = self.M["buttons"]["record"]
        self.cv.create_text(S(bx), S(by), text=label, fill=ink,
                            font=(family, -max(9, int(S(17))), "bold"), tags="dyn")
        # The status line ends before the MIDI badge (midi_in draws it on the same bar)
        # or before the parchment, cut with an ellipsis when it is too long.
        x, y = S(self.M["status"][0]), S(self.M["status"][1])
        right = S(self.M.get("status_right", 1325))
        badge = self.cv.bbox("midi")
        if badge and badge[0] > x:
            right = min(right, badge[0] - S(16))
        font = self._font(max(8, int(S(11))))
        self.cv.create_text(x, y, anchor="w", text=fit_text(msg, font, right - x),
                            fill=self.M["status_fg"], font=font, tags="dyn")

    def _font(self, size):
        """The status line's font at this size, kept so the text can be measured."""
        fonts = self.__dict__.setdefault("_fonts", {})
        key = (self.M["font"], size)
        if key not in fonts:
            fonts[key] = tkfont.Font(root=self.root, family=key[0], size=size)
        return fonts[key]

    def _to_img(self, e):
        return e.x / self.scale, e.y / self.scale

    def _knob_at(self, x, y):
        for k, (cx, cy, r, vx, vy) in self.M["knobs"].items():
            if (x - cx) ** 2 + (y - cy) ** 2 <= (r + 6) ** 2:
                return k
        return None

    def _hit(self, x, y, cx, cy, hw, hh):
        return cx - hw <= x <= cx + hw and cy - hh <= y <= cy + hh

    def _click(self, e):
        x, y = self._to_img(e)
        k = self._knob_at(x, y)
        if k:
            self._drag = (k, y)
            return
        for w, (wx, wy) in self.M["waveform"].items():
            if self._hit(x, y, wx, wy, 42, 16):
                self.waveform = w
                self._changed()
                return
        by = self.M["banks_y"]
        for i, bx in enumerate(self.M["banks"]):
            if self._hit(x, y, bx, by, 30, 20):
                self._switch_bank(i)
                return
        for name, b in self.M["buttons"].items():
            if self._hit(x, y, b[0], b[1], b[2], b[3]):
                self._button(name)
                return
        px0, py0, px1, py1 = self.M["piano"]
        if px0 <= x <= px1 and py0 <= y <= py1:
            self._piano_hit(x, y, px0, py0, px1, py1)
            return
        C = self.M["cells"]
        for i, cx in enumerate(C["cx"]):
            if self._hit(x, y, cx, C["cy"], C["hw"], C["hh"]):
                self.sel = i
                self.refresh()
                return

    def _motion(self, e):
        if not self._drag:
            return
        k, lasty = self._drag
        _, y = self._to_img(e)
        vmin, vmax = KNOB_SPEC[k][0], KNOB_SPEC[k][1]
        self.kv[k] = min(vmax, max(vmin, self.kv[k] - (y - lasty) * (vmax - vmin) / 150.0))
        self._drag = (k, y)
        self._knob_live(k)

    def _wheel(self, e):
        x, y = self._to_img(e)
        k = self._knob_at(x, y)
        if not k:
            return
        vmin, vmax = KNOB_SPEC[k][0], KNOB_SPEC[k][1]
        step = (vmax - vmin) / 40.0
        up = getattr(e, "num", None) == 4 or getattr(e, "delta", 0) > 0
        self.kv[k] = min(vmax, max(vmin, self.kv[k] + (step if up else -step)))
        self._knob_live(k)

    def _piano_hit(self, x, y, px0, py0, px1, py1):
        letters = "CDEFGAB"
        nwhite = 21                              # 3 octaves of white keys (C..B x3)
        ww = (px1 - px0) / nwhite
        wi = min(nwhite - 1, max(0, int((x - px0) / ww)))
        # black keys live on the upper ~60% of the keyboard, centered on the boundary
        # after C, D, F, G, A (white letter index 0,1,3,4,5 -> C#,D#,F#,G#,A#)
        if y <= py0 + 0.60 * (py1 - py0):
            for cand in (wi, wi - 1):
                if 0 <= cand < nwhite - 1 and (cand % 7) in (0, 1, 3, 4, 5):
                    center = px0 + (cand + 1) * ww
                    if abs(x - center) <= 0.32 * ww:
                        self._set_note(f"{letters[cand % 7]}#{1 + cand // 7}")
                        return
        self._set_note(f"{letters[wi % 7]}{1 + wi // 7}")

    def _button(self, name):
        {"run": self._toggle_run, "stop": self._stop,
         "accent": lambda: self._toggle_step("accent"), "slide": lambda: self._toggle_step("slide"),
         "oct_down": lambda: self._octave(-1), "oct_up": lambda: self._octave(1),
         "rest": lambda: self._set_note(None), "record": self._toggle_record, "clear": self._clear,
         "demo": lambda: (self._load_pattern(DEMO_PATTERN), setattr(self, "sel", 0), self._changed())}[name]()

    def _apply_preset(self, name):
        p = PRESETS.get(name)
        if not p:
            return
        self.waveform = p["waveform"]
        for k in ("cutoff", "resonance", "env_mod", "decay", "accent", "distortion", "shuffle"):
            self.kv[k] = p[k]
        self._changed()

    def _capture_settings(self):
        """Snapshot the sound (knobs + waveform + scale + play mode) of the current bank."""
        return {"knobs": dict(self.kv), "waveform": self.waveform,
                "scale": self.scale_v.get(), "playmode": self.playmode_v.get()}

    def _apply_settings(self, s):
        if not s:
            return
        for k, v in s.get("knobs", {}).items():
            if k in self.kv:
                lo, hi = KNOB_SPEC[k][0], KNOB_SPEC[k][1]
                self.kv[k] = min(hi, max(lo, float(v)))
        self.waveform = s.get("waveform", self.waveform)
        if "scale" in s:
            self.scale_v.set(s["scale"])
        if "playmode" in s:
            self.playmode_v.set(s["playmode"])

    def _switch_bank(self, b):
        self._freeze_bank()
        self._enter_bank(b)

    def _freeze_bank(self):
        """Store the current bank: its steps, its knob settings and its instrument."""
        self.banks[self.cur_bank] = [dict(s) for s in self.steps]
        self.bank_settings[self.cur_bank] = self._capture_settings()
        self.bank_instr[self.cur_bank] = self.instrument

    def _enter_bank(self, b):
        """Make bank b the current one, WITHOUT storing the bank being left first
        (the caller has either frozen it or deliberately replaced it)."""
        self.cur_bank = b
        if self.banks[b] is None:
            self.banks[b] = [{"note": None, "accent": False, "slide": False} for _ in range(16)]
            self.bank_instr[b] = self.instrument  # a never-used bank inherits the instrument
        if self.bank_settings[b] is not None:    # recall this bank's own sound
            self._apply_settings(self.bank_settings[b])
        # (a never-used bank keeps the current sound, then gets its own copy when you leave it)
        self.steps = [dict(s) for s in self.banks[b]]
        self.sel = 0
        if self.bank_instr[b] != self.instrument:
            self._set_instrument(self.bank_instr[b])
        self._changed()

    def _set_note(self, note):
        self.steps[self.sel]["note"] = note
        self._preview(note)
        self.sel = (self.sel + 1) % 16
        self._changed()

    def _toggle_step(self, key):
        self.steps[self.sel][key] = not self.steps[self.sel][key]
        self._changed()

    def _octave(self, d):
        n = self.steps[self.sel]["note"]
        if n:
            self.steps[self.sel]["note"] = f"{n[:-1]}{int(n[-1]) + d}"
            self._changed()

    def _params(self):
        return dict(bpm=self.kv["bpm"], waveform=self.waveform, cutoff=self.kv["cutoff"],
                    resonance=self.kv["resonance"], env_mod=self.kv["env_mod"], decay=self.kv["decay"],
                    accent=self.kv["accent"], distortion=self.kv["distortion"], tuning=self.kv["tuning"],
                    swing=self.kv["shuffle"], subdiv=SCALE_MAP[self.scale_v.get()],
                    play_mode=PLAYMODES[self.playmode_v.get()])

    def _render(self, repeats=1):
        a = self.tb.render([dict(s) for s in self.steps], repeats=repeats, **self._params())
        return np.clip(a * self.kv["volume"] / 0.9, -1, 1)

    def _preview(self, note):
        if not note:
            return
        if not self._is303():
            if self._instr_rt and self.irt is not None:
                self.irt.preview(note)
                self._flash_note(note)
            else:
                self._preview_instr(note)
            return
        if not self.audio_ok:
            return
        if self.mode == "rt" and self.rt is not None:
            self.rt.preview(note)               # real-time audition
            self._flash_note(note)
            return
        try:
            p = self._params()
            p.update(bpm=80, subdiv=1, swing=0.0, play_mode="forward")
            a = self.tb.render([{"note": note, "accent": False, "slide": False}], repeats=1, **p)
            a = np.clip(a * self.kv["volume"] / 0.9, -1, 1)
            self._ps = pygame.sndarray.make_sound(np.ascontiguousarray((a * 0.9 * 32767).astype(np.int16)))
            self._ps.play()
            self._flash_note(note, len(a) / self.SR)
        except Exception:
            pass

    def _changed(self):
        self.refresh()
        if not self._is303():
            if self._instr_rt and self.irt is not None:
                self._irt_push_all()              # live params + pattern, no re-render
            elif self.playing:
                self._play_instr()
            return
        if self.mode == "rt" and self.rt is not None:
            try:
                self._push_rt()                   # real-time: instant update
            except Exception as e:
                self.audio_err = f"push KO ({e})"
        elif self.playing and self.audio_ok:
            self._play_loop()                     # pygame: re-render the loop

    def _play_loop(self):
        try:
            a = self._render(1)
            self._loop_audio = a[:, 0] if a.ndim == 2 else a
            self._loop_dur = max(1e-3, len(a) / self.SR)
            self._loop_t0 = time.monotonic()
            d = np.ascontiguousarray((np.clip(a, -1, 1) * 32767).astype(np.int16))
            pygame.mixer.stop()
            self._snd = pygame.sndarray.make_sound(d)
            self._snd.play(loops=-1)
        except Exception as e:
            self.playing = False
            self.audio_err = f"RUN KO ({e})"
            self.refresh()

    def _toggle_run(self):
        if not self._is303():
            self._toggle_instr()
            return
        if not self.audio_ok:
            messagebox.showinfo(
                "Audio unavailable",
                "The audio engine is not active: " + (self.audio_err or "pygame missing") + ".\n\n"
                "So RUN has nothing to play (the button works, there is just no sound).\n\n"
                "In the terminal where you launch the script:\n"
                "    pip install pygame   (ou : pip install sounddevice numba)\n"
                "then relaunch.  (File > Export WAV works without audio.)")
            return
        if self.mode == "rt":
            self.playing = not self.playing
            if self.playing:
                self._push_rt()
                self.rt.set_playing(True)
                self._vu_start()
            else:
                self.rt.set_playing(False)
                self._vu_stop()
            self.refresh()
            return
        if self.playing:
            self._stop()
        else:
            self.playing = True
            self._play_loop()
            self._vu_start()
            self.refresh()

    def _stop(self):
        self.playing = False
        self._vu_stop()
        if not self._is303():
            if self._instr_rt and self.irt is not None:
                self.irt.set_playing(False)
            elif _HAS_PYGAME and pygame.mixer.get_init():
                pygame.mixer.stop()
        elif self.mode == "rt" and self.rt is not None:
            self.rt.set_playing(False)
        elif self.audio_ok and _HAS_PYGAME:
            pygame.mixer.stop()
        self.refresh()

    def close(self):
        self._discard_take()
        self._vu_stop()
        if self._mixer_tap is not None:
            self._mixer_tap.close()
            self._mixer_tap = None
        job = getattr(self, "_import", None)
        if job is not None:                      # an audio import still running: stop it
            try:
                job["proc"].kill()
                os.remove(job["tmp"])
            except Exception:
                pass
        try:
            if self.rt is not None:
                self.rt.stop()
        except Exception:
            pass
        try:
            if self.irt is not None:
                self.irt.stop()
        except Exception:
            pass

    # ---------- VU meters: the steampunk lamps themselves brighten with the music ----------
    NLAMPFR = 14

    def _build_lamp_frames(self):
        """Pre-render, for each lamp, a set of brightness frames of just the bulb glass
        (dark -> glowing), blended through a soft radial mask so only the glass changes
        and the edges fade seamlessly into the panel (no halo)."""
        sc = self.scale
        src = self._disp_rgb
        sw, sh = src.size
        for item in self._lamp_items:
            self.cv.delete(item)
        self._lamp_items, self._lamp_frames, self._lamp_pos = [], [], []
        if self._lighting is not None:
            self._lighting.close()
            self._lighting = None
        if self._skin in STYLES:
            self._lighting = SkinLights(self.cv, self.scale, self.M, self._skin)
            self._update_lighting()
            return
        lamp_color = np.array(self.M["lamp_color"])
        for (cx, cy, r) in self.M["lamps"]:
            X, Y, R = cx * sc, cy * sc, max(6.0, r * sc)
            box = int(R * 1.7)
            x0, y0 = max(0, int(X - box)), max(0, int(Y - box))
            x1, y1 = min(sw, int(X + box)), min(sh, int(Y + box))
            region = np.asarray(src.crop((x0, y0, x1, y1))).astype(float)
            rh, rw = region.shape[:2]
            yy, xx = np.mgrid[0:rh, 0:rw]
            d = np.sqrt((xx - (X - x0)) ** 2 + (yy - (Y - y0)) ** 2)
            m = (np.clip(1.0 - (d / (R * 1.25)) ** 2, 0, 1) ** 1.3)[..., None]
            frames = []
            for k in range(self.NLAMPFR):
                f = k / (self.NLAMPFR - 1)
                if f < 0.5:                                  # dark -> normal
                    proc = region * (0.30 + (f / 0.5) * 0.70)
                else:                                        # normal -> blazing (warm screen)
                    t = (f - 0.5) / 0.5
                    warm = lamp_color * t
                    proc = (255 - (255 - region) * (255 - warm) / 255) * (1 + 0.25 * t)
                comp = region * (1 - m) + np.clip(proc, 0, 255) * m
                frames.append(ImageTk.PhotoImage(
                    Image.fromarray(np.clip(comp, 0, 255).astype(np.uint8))))
            self._lamp_frames.append(frames)
            self._lamp_pos.append((x0, y0))
            self._lamp_items.append(self.cv.create_image(x0, y0, anchor="nw",
                                                          image=frames[self._rest_idx()]))

    def _rest_idx(self):
        return max(1, int(0.12 * (self.NLAMPFR - 1)))        # faint standby when silent

    def _set_lamps(self, idx):
        idx = max(0, min(self.NLAMPFR - 1, idx))
        for it, frames in zip(self._lamp_items, self._lamp_frames):
            self.cv.itemconfig(it, image=frames[idx])

    def _vu_start(self):
        if not self._vu_on:
            self._vu_on = True
            self._vu_tick()

    def _flash_note(self, note, duration=.5):
        self._audition_note = note
        self._audition_until = time.monotonic() + duration
        self._vu_start()

    def _vu_stop(self):
        self._vu_on = False
        if self._vu_job is not None:
            self.root.after_cancel(self._vu_job)
            self._vu_job = None
        self._audition_until = 0.0
        self._audition_note = None
        self.level = 0.0
        self._set_lamps(self._rest_idx())
        self._update_lighting()

    def _active_engine(self):
        if self._is303():
            return self.rt if self.mode == "rt" else None
        return self.irt if self._instr_rt else None

    def _vu_level(self):
        engine = self._active_engine()
        if engine is not None:
            return min(1.0, engine.get_level())
        if self._mixer_tap is not None:
            return self._mixer_level
        if self.playing and self._loop_audio is not None and self._loop_dur > 0:
            pos = (time.monotonic() - self._loop_t0) % self._loop_dur
            i = int(pos * self.SR)
            w = self._loop_audio[i:i + 1024]
            if len(w):
                return float(min(1.0, np.sqrt(np.mean(w * w)) * 3.2))
        return 0.0

    def _update_lighting(self):
        if self._lighting is None:
            return
        now = time.monotonic()
        note = self._audition_note if now < self._audition_until else None
        step = None
        if self.playing and self._vu_on:
            engine = self._active_engine()
            if engine is not None:
                step = engine.get_step()
            elif self._loop_audio is not None:
                # The offline loop alternates long/short steps when shuffle is on.
                position = (now - self._loop_t0) % self._loop_dur
                slot = position / self._loop_dur * len(self.steps)
                pair = int(slot // 2)
                step = 2 * pair + int(slot - 2 * pair >= 1 + self.kv["shuffle"])
        self._lighting.show(self.level, step, note)

    def _vu_tick(self):
        self._vu_job = None
        if not self.playing and time.monotonic() >= self._audition_until:
            self._vu_stop()
            return
        lv = self._vu_level()
        self.level = lv if lv > self.level else self.level * 0.78    # fast rise, slow fall
        self._set_lamps(int(round(self.level * (self.NLAMPFR - 1))))
        self._update_lighting()
        self._vu_job = self.root.after(34, self._vu_tick)

    # ---------- instruments (non-303 voices) ----------
    def _is303(self):
        return self.instrument == "TB-303"

    def _voice(self):
        if self.instrument in instruments.BUILTIN:
            return instruments.BUILTIN[self.instrument]
        if self.instrument in self.samples:
            return self.samples[self.instrument]["sampler"].note
        return None

    # ---------- instrument menu, sample library ----------
    def _instr_label(self, iid):
        return iid if not iid.startswith(SAMPLE_PREFIX) else "♫ " + iid[len(SAMPLE_PREFIX):]

    AUDIO_EXT = (".wav", ".flac", ".ogg", ".mp3", ".aiff", ".aif", ".m4a", ".aac",
                 ".opus", ".wma")

    @classmethod
    def _library_files(cls):
        """Audio files sitting in Instruments/, i.e. every sample ever used."""
        try:
            names = os.listdir(INSTRUMENTS_DIR)
        except OSError:
            return []
        return sorted((n for n in names
                       if n.lower().endswith(cls.AUDIO_EXT) and not n.startswith(".")
                       and os.path.isfile(os.path.join(INSTRUMENTS_DIR, n))), key=str.lower)

    def _rebuild_instr_menu(self):
        """TB-303 and the built-in voices, then every sample of Instruments/ --
        each selectable, with a tick on the instrument of the current pattern.
        A sample is only decoded the first time it is chosen."""
        m = self.instr_menu
        m.delete(0, "end")
        for iid in [TB303_ID] + list(instruments.BUILTIN.keys()):
            m.add_radiobutton(label=iid, variable=self._instr_var, value=iid,
                              command=lambda n=iid: self._set_instrument(n))
        names = set(self._library_files()) | {e["name"] for e in self.samples.values()}
        if names:
            m.add_separator()
            for name in sorted(names, key=str.lower):
                iid = SAMPLE_PREFIX + name
                m.add_radiobutton(label=self._instr_label(iid), variable=self._instr_var,
                                  value=iid, command=lambda n=name: self._choose_library(n))
        m.add_separator()
        m.add_command(label="Load sample…", command=self._load_sample)
        self._instr_var.set(self.instrument)

    def _choose_library(self, name):
        """A sample of Instruments/ picked from the menu: decode it if needed."""
        iid = SAMPLE_PREFIX + name
        if iid not in self.samples:
            try:
                self._register_sample(os.path.join(INSTRUMENTS_DIR, name))
            except Exception as e:
                self._instr_var.set(self.instrument)     # keep the tick where it was
                messagebox.showerror("Cannot load sample", f"{name}\n\n{e}")
                return
        self._set_instrument(iid)

    @staticmethod
    def _copy_into_instruments(src):
        """Copy a sample into Instruments/ and return the copy's path. A file of the
        same name and content is reused; same name, other content -> name-2.wav."""
        os.makedirs(INSTRUMENTS_DIR, exist_ok=True)
        src = os.path.abspath(src)
        if os.path.dirname(src) == os.path.abspath(INSTRUMENTS_DIR):
            return src
        base, ext = os.path.splitext(os.path.basename(src))
        k = 1
        while True:
            name = f"{base}{ext}" if k == 1 else f"{base}-{k}{ext}"
            dst = os.path.join(INSTRUMENTS_DIR, name)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
                return dst
            if filecmp.cmp(src, dst, shallow=False):
                return dst
            k += 1

    def _register_sample(self, path, base_freq=None, sampler=None, origin=None):
        """Load a sample that already sits in Instruments/ and add it to the menu.
        `origin` is where the file was first picked from, kept as a fallback for
        when the copy goes missing. Returns its instrument id. Raises if the file
        cannot be decoded."""
        name = os.path.basename(path)
        iid = SAMPLE_PREFIX + name
        if iid not in self.samples:
            smp = sampler or instruments.Sampler.from_wav(path, base_freq)
            self.samples[iid] = {"name": name, "path": path, "sampler": smp,
                                 "origin": os.path.abspath(origin or path)}
            self._rebuild_instr_menu()
        return iid

    def _ensure_pygame(self):
        if not _HAS_PYGAME:
            return False
        if not pygame.mixer.get_init():
            if os.path.exists("/mnt/wslg/PulseServer"):
                os.environ.setdefault("SDL_AUDIODRIVER", "pulseaudio")
                os.environ["PULSE_SERVER"] = "unix:/mnt/wslg/PulseServer"
            try:
                pygame.mixer.init(frequency=self.SR, size=-16, channels=2, allowedchanges=0)
            except Exception:
                return False
            self._mixer_error = None
        if self._mixer_tap is None and self._mixer_error is None:
            self._install_mixer_tap()
        return True

    def _install_mixer_tap(self):
        try:
            self._mixer_tap = MixerOutputTap(pygame.mixer, self.SR, self._mixer_audio)
            self._mixer_error = None
        except RuntimeError as error:
            self._mixer_error = str(error)

    def _mixer_audio(self, pcm):
        samples = np.frombuffer(pcm, dtype=np.int16)
        if samples.size:
            self._mixer_level = max(int(samples.max()), -int(samples.min())) / 32768
        take = self._mixer_take
        if take is not None:
            take.capture_pcm(pcm)

    # ---------- real-time instrument engine (sample + 303 filter, live knobs) ----------
    def _ensure_irt(self):
        """Start the sampler's stream. The 303's stream stays open beside it when the
        sound system allows it (PulseAudio, PipeWire): changing pattern then only
        changes which engine plays, with no stream to close and reopen; closing one
        while it played could hang the studio. A device that takes one stream at a
        time gets them in turn."""
        if not self.irt_ok:
            return False
        try:
            if self.irt is None:
                self.irt = instruments_rt.RealtimeSamplerEngine(sr=self.SR)
            if self.irt.stream is None:
                if self._one_stream:
                    self._close_rt_stream()
                try:
                    self.irt.start()
                except Exception:
                    if self._one_stream or not self._close_rt_stream():
                        raise
                    self._one_stream = True
                    self.irt.start()
            return True
        except Exception:
            self.irt_ok = False
            return False

    def _close_rt_stream(self):
        """Free the device from the 303's stream; False when it had none open."""
        if self.mode != "rt" or self.rt is None or self.rt.stream is None:
            return False
        try:
            self.rt.stop()
        except Exception:
            pass
        return True

    def _resume_303(self):
        if self._one_stream and self.irt is not None:
            try:
                self.irt.stop()
            except Exception:
                pass
        if self.mode == "rt" and self.rt is not None:
            try:
                self.rt.start()                  # nothing to do when its stream is open
            except Exception:
                pass

    # `e` (optional) is another RealtimeSamplerEngine to set up the same way (the WAV export).
    def _irt_load_voice(self, e=None):
        e = self.irt if e is None else e
        if e is None:
            return
        if self.instrument in self.samples:
            smp = self.samples[self.instrument]["sampler"]
            e.set_sample(smp.s, smp.base)
        elif self.instrument in instruments.BUILTIN:
            s, b = instruments_rt.reference_sample(self.instrument, self.SR)
            e.set_sample(s, b)

    def _irt_push_pattern(self, e=None):
        e = self.irt if e is None else e
        steps = apply_play_mode([dict(s) for s in self.steps], PLAYMODES[self.playmode_v.get()])
        e.set_pattern([(s["note"], s["accent"], s["slide"]) for s in steps])

    def _irt_push_all(self, e=None):
        e = self.irt if e is None else e
        if e is None:
            return
        for k in ("cutoff", "resonance", "env_mod", "decay", "accent", "bpm",
                  "distortion", "volume", "tuning"):
            e.set_param(k, self.kv[k])
        e.set_param("swing", self.kv["shuffle"])
        e.set_param("subdiv", SCALE_MAP[self.scale_v.get()])
        self._irt_push_pattern(e)

    def _irt_set_param(self, k):
        if self.irt is None:
            return
        self.irt.set_param("swing" if k == "shuffle" else k, self.kv[k])

    def _set_instrument(self, name):
        """Give the CURRENT pattern this instrument (TB-303, a built-in voice or a
        loaded sample). Each of the 8 patterns keeps its own."""
        if name != TB303_ID and name not in instruments.BUILTIN and name not in self.samples:
            name = TB303_ID                       # unknown id (e.g. sample removed)
        take = self._take
        switching_at = None
        if take is not None and take.recording:
            self._disconnect_take()
            switching_at = time.monotonic()
        was = self.playing
        self._stop()
        self.instrument = name
        self.bank_instr[self.cur_bank] = name
        self._instr_var.set(name)
        self._instr_rt = False
        if name == TB303_ID:
            self._resume_303()
        elif self.irt_ok and self._ensure_irt():
            self._instr_rt = True
            self._irt_load_voice()
            self._irt_push_all()
        if switching_at is not None:
            take.add_silence(time.monotonic() - switching_at)
            try:
                self._connect_take()
            except (OSError, RuntimeError) as error:
                self._finish_take()
                messagebox.showwarning("Recording stopped", str(error), parent=self.root)
        if was:
            self._toggle_run()
        self.refresh()

    def _load_sample(self):
        """Bring a new sound into the studio for the current pattern. No
        initialdir: the chooser reopens where the last sample came from. Samples
        already in Instruments/ are picked straight from the Instrument menu."""
        path = filedialog.askopenfilename(
            title="Charger un sample pour ce pattern",
            filetypes=[("Audio", "*.wav *.flac *.ogg *.mp3 *.aiff *.aif *.m4a *.aac *.opus *.wma"),
                       ("Tous les fichiers", "*.*")])
        if not path:
            return
        try:
            smp = instruments.Sampler.from_wav(path)   # decode first: never copy junk
            iid = self._register_sample(self._copy_into_instruments(path), sampler=smp,
                                        origin=path)
        except Exception as e:
            messagebox.showerror("Cannot load sample",
                                 f"{e}\n\n(For mp3/m4a/... soundfile or ffmpeg must be installed.)")
            return
        self._set_instrument(iid)

    def _render_instr(self, repeats):
        v = self._voice()
        if v is None:
            return np.zeros((1, 2))
        a = instruments.render_pattern(
            self.steps, v, bpm=int(self.kv["bpm"]), subdiv=SCALE_MAP[self.scale_v.get()],
            swing=self.kv["shuffle"], play_mode=PLAYMODES[self.playmode_v.get()],
            repeats=repeats, tuning=self.kv["tuning"],
            cutoff=self.kv["cutoff"], resonance=self.kv["resonance"],
            env_mod=self.kv["env_mod"], decay=self.kv["decay"],
            distortion=self.kv["distortion"])
        return np.clip(a * self.kv["volume"], -1, 1)

    def _play_instr(self):
        if not self._ensure_pygame():
            return
        try:
            a = self._render_instr(1)
            self._loop_audio = a[:, 0] if a.ndim == 2 else a
            self._loop_dur = max(1e-3, len(a) / self.SR)
            self._loop_t0 = time.monotonic()
            pygame.mixer.stop()
            self._snd = pygame.sndarray.make_sound(
                np.ascontiguousarray((a * 32767).astype(np.int16)))
            self._snd.play(loops=-1)
        except Exception as e:
            self.playing = False
            self.audio_err = f"instr KO ({e})"

    def _toggle_instr(self):
        if self._instr_rt and self.irt is not None:
            if self.mode == "rt" and self.rt is not None:
                self.rt.set_playing(False)
            self.playing = not self.playing
            if self.playing:
                self._irt_load_voice()
                self._irt_push_all()
                self.irt.set_playing(True)
                self._vu_start()
            else:
                self.irt.set_playing(False)
                self._vu_stop()
            self.refresh()
            return
        if not self._ensure_pygame():
            messagebox.showinfo("Audio", "Instrument playback needs pygame:\n    pip install pygame")
            return
        if self.mode == "rt" and self.rt is not None:
            self.rt.set_playing(False)
        self.playing = not self.playing
        if self.playing:
            self._play_instr()
            self._vu_start()
        elif pygame.mixer.get_init():
            pygame.mixer.stop()
            self._vu_stop()
        self.refresh()

    def _preview_instr(self, note):
        if not self._ensure_pygame():
            return
        v = self._voice()
        if v is None:
            return
        try:
            n = v(instruments.note_to_freq(note, self.kv["tuning"]), 0.4, False)
            a = np.clip(n * self.kv["volume"], -1, 1)
            self._ps = pygame.sndarray.make_sound(
                np.ascontiguousarray((np.column_stack([a, a]) * 32767).astype(np.int16)))
            self._ps.play()
            self._flash_note(note, len(a) / self.SR)
        except Exception:
            pass

    def _bounce(self, repeats=4):
        """`repeats` loops of the current pattern, computed by the real-time engine
        that plays it, on a second engine set up exactly like the live one -- so
        the file is what comes out of the speakers. None when no real-time engine
        plays this pattern: playback is then the offline render (pygame), and so
        must the file be."""
        sr = float(self.SR)
        if self._is303():
            if self.mode != "rt" or self.rt is None:
                return None
            import tb303_rt
            e = RealtimeEngine(sr=self.SR)
            self._push_rt(e)
            def block(buf):
                tb303_rt.synth_block(buf, len(buf), e.state, e.params,
                                     e.pat_f, e.pat_a, e.pat_s, e.nsteps, sr)
        else:
            if not (self._instr_rt and self.irt is not None):
                return None
            e = instruments_rt.RealtimeSamplerEngine(sr=self.SR)
            self._irt_load_voice(e)
            self._irt_push_all(e)
            def block(buf):
                instruments_rt.synth_block(buf, len(buf), e.state, e.params,
                                           e.pat_f, e.pat_a, e.pat_s, e.nsteps, sr,
                                           e.sample, e.sample.size, e.base)
        # one loop = the engine's own step lengths (play mode and swing included)
        step = sr * 60.0 / max(self.kv["bpm"], 1.0) / max(SCALE_MAP[self.scale_v.get()], 1)
        sw = self.kv["shuffle"]
        loop = sum(step * ((1.0 + sw) if i % 2 == 0 else (1.0 - sw)) for i in range(e.nsteps))
        n = int(round(loop * repeats))
        e.set_playing(True)
        out = np.empty(n)
        for a in range(0, n, 4096):
            buf = np.empty(min(4096, n - a))
            block(buf)
            out[a:a + len(buf)] = buf
        out = np.clip(out, -1.0, 1.0)
        return np.column_stack([out, out])

    def _save(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".wav", initialfile="tb303.wav",
            filetypes=[("WAV", "*.wav"), ("FLAC", "*.flac"), ("OGG", "*.ogg"),
                       ("MP3", "*.mp3"), ("AIFF", "*.aiff"), ("Tous les fichiers", "*.*")])
        if not path:
            return
        try:
            audio = self._bounce(4)
        except Exception as e:
            print(f"export through the real-time engine failed ({e}): offline render used")
            audio = None
        if audio is None:
            audio = self._render(4) if self._is303() else self._render_instr(4)
        try:
            if path.lower().endswith(".wav"):
                self.tb.write_wav(audio, path)
            else:
                instruments.write_audio(audio, path, sr=self.SR)
        except Exception as e:
            messagebox.showerror("Cannot export", str(e))

    # ---------- Live WAV recording ----------

    def _connect_take(self):
        if self._is303() and not self.audio_ok:
            raise RuntimeError(self.audio_err or "The audio output is unavailable.")
        engine = self._active_engine()
        if engine is not None:
            if engine.stream is None or not engine.stream.active:
                raise RuntimeError("The real-time audio output is unavailable.")
            self._record_engine = engine
            engine.output_tap = self._take.capture_float
        elif self._ensure_pygame():
            if self._mixer_tap is None:
                raise RuntimeError(self._mixer_error or "This pygame output cannot be recorded.")
            self._mixer_take = self._take
        else:
            raise RuntimeError("The pygame audio output is unavailable.")

    def _disconnect_take(self):
        if self._record_engine is not None:
            self._record_engine.output_tap = None
            self._record_engine = None
        self._mixer_take = None

    def _toggle_record(self):
        if self._take is None:
            try:
                self._take = WaveTake(self.SR)
                self._connect_take()
            except (OSError, RuntimeError) as error:
                self._discard_take()
                messagebox.showerror("Cannot start recording", str(error), parent=self.root)
            self.refresh()
            return
        if self._take.recording:
            self._finish_take()
        if self._take is not None:
            self._save_take()

    def _finish_take(self):
        self._disconnect_take()
        take = self._take
        take.finish()
        if take.error is not None:
            messagebox.showwarning("Recording interrupted", str(take.error), parent=self.root)
        if not take.frames:
            self._discard_take()
            if take.error is None:
                messagebox.showinfo("Record", "No audio samples were received.", parent=self.root)
        self.refresh()

    def _save_take(self, *, closing=False):
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Save live recording", defaultextension=".wav",
            initialfile=time.strftime("tb303-take-%Y%m%d-%H%M%S.wav"), filetypes=[("WAV", "*.wav")])
        if not path:
            if not closing and messagebox.askyesno(
                    "Discard recording?", "Discard this take? Choose No to keep it for later.",
                    parent=self.root):
                self._discard_take()
                self.refresh()
            return False
        if not path.lower().endswith(".wav"):
            path += ".wav"
            if os.path.exists(path) and not messagebox.askyesno(
                    "Replace recording?", f"Replace {os.path.basename(path)}?", parent=self.root):
                return False
        try:
            self._take.save(path)
        except OSError as error:
            messagebox.showerror("Cannot save recording", str(error), parent=self.root)
            return False
        self._discard_take()
        self.refresh()
        return True

    def _discard_take(self):
        self._disconnect_take()
        if self._take is not None:
            self._take.close()
            self._take = None

    def _confirm_close_recording(self):
        if self._take is None:
            return True
        if self._take.recording:
            self._finish_take()
        if self._take is None:
            return True
        save = messagebox.askyesnocancel("Unsaved recording", "Save the recording before closing?",
                                         parent=self.root)
        return save is False or (save is True and self._save_take(closing=True))

    # ---------- .tb303 project: per-pattern save / load ----------
    #
    # File format v3 = v2 + "bank_instruments" (+ "patterns_saved"). The 8-slot
    # lists stay 8 long; a pattern that was not saved is null in all of them, so
    # an older studio can still open the file (it just ignores the instruments).

    def _instr_descriptor(self, iid):
        if iid in self.samples:
            e = self.samples[iid]
            return {"kind": "sample", "name": e["name"],
                    "file": e["name"],              # its name in Instruments/
                    "source": e.get("origin") or os.path.abspath(e["path"]),
                    "base_freq": round(float(e["sampler"].base), 4)}
        if iid in instruments.BUILTIN:
            return {"kind": "builtin", "name": iid}
        return {"kind": "tb303", "name": TB303_ID}

    @staticmethod
    def _descriptor_label(desc):
        if not desc or desc.get("kind") in (None, "tb303"):
            return TB303_ID
        if desc.get("kind") == "sample":
            return "♫ " + (desc.get("file") or desc.get("name") or "?")
        return desc.get("name") or "?"

    @staticmethod
    def _pattern_notes(steps):
        return sum(1 for s in (steps or []) if s and s.get("note"))

    @classmethod
    def _summary(cls, steps, instr_label):
        n = cls._pattern_notes(steps)
        if steps is None or n == 0:
            return f"{instr_label}  ·  empty"
        return f"{instr_label}  ·  {n} note{'s' if n > 1 else ''}"

    def _project_state(self, include=None):
        """include: iterable of 0-based patterns to save; None or empty = all 8."""
        self._freeze_bank()
        inc = set(range(N_BANKS)) if not include else set(include)
        cur = self.cur_bank if self.cur_bank in inc else min(inc)
        top = self.bank_settings[cur] or self._capture_settings()
        banks, settings, instr = [], [], []
        for i in range(N_BANKS):
            b = self.banks[i] if i in inc else None
            s = self.bank_settings[i] if (i in inc and b is not None) else None
            banks.append(None if b is None else [dict(x) for x in b])
            settings.append(None if s is None else {
                "knobs": {k: round(float(v), 4) for k, v in s["knobs"].items()},
                "waveform": s["waveform"], "scale": s["scale"], "playmode": s["playmode"]})
            instr.append(None if b is None else self._instr_descriptor(self.bank_instr[i]))
        return {
            "format": "tb303-studio", "version": PROJECT_VERSION,
            "patterns_saved": sorted(i + 1 for i in inc),
            "knobs": {k: round(float(v), 4) for k, v in top["knobs"].items()},
            "waveform": top["waveform"], "scale": top["scale"], "playmode": top["playmode"],
            "preset": self.preset_v.get(),
            "cur_bank": cur,
            "banks": banks, "bank_settings": settings, "bank_instruments": instr,
        }

    @staticmethod
    def _read_project(path):
        """Read a .tb303 file of any version into one normalised shape:
        {"banks": [8], "settings": [8], "instr": [8], "cur": int, "top": {...}}."""
        with open(path, "r", encoding="utf-8") as f:
            st = json.load(f)
        if not isinstance(st, dict) or st.get("format") != "tb303-studio":
            raise ValueError("This file is not a TB-303 project.")

        def eight(key):
            v = st.get(key)
            return list(v) if isinstance(v, list) and len(v) == N_BANKS else [None] * N_BANKS

        banks = []
        for b in eight("banks"):
            banks.append(None if b is None else
                         [{"note": s.get("note"), "accent": bool(s.get("accent")),
                           "slide": bool(s.get("slide"))} for s in b])
        settings = []
        for s in eight("bank_settings"):
            settings.append(None if s is None else {
                "knobs": dict(s.get("knobs", {})), "waveform": s.get("waveform", "square"),
                "scale": s.get("scale", "1/16"), "playmode": s.get("playmode", "Forward")})
        instr = eight("bank_instruments")
        top = {"knobs": dict(st.get("knobs", {})), "waveform": st.get("waveform", "square"),
               "scale": st.get("scale", "1/16"), "playmode": st.get("playmode", "Forward"),
               "preset": st.get("preset")}
        cur = int(st.get("cur_bank", 0)) % N_BANKS
        if banks[cur] is not None and settings[cur] is None:
            settings[cur] = {k: top[k] for k in ("knobs", "waveform", "scale", "playmode")}
        for i in range(N_BANKS):
            if banks[i] is not None and not instr[i]:
                instr[i] = {"kind": "tb303", "name": TB303_ID}     # v2: all TB-303
        return {"banks": banks, "settings": settings, "instr": instr, "cur": cur, "top": top}

    def _resolve_instr(self, desc, project_path, warnings):
        """Instrument descriptor from a file -> instrument id usable here. A sample
        is looked for in Instruments/, next to the project, then at its original
        place, and copied into Instruments/ when found elsewhere."""
        kind = (desc or {}).get("kind")
        name = (desc or {}).get("name")
        if kind == "builtin":
            if name in instruments.BUILTIN:
                return name
            warnings.append(f"Built-in instrument “{name}” is not in this version: TB-303 used.")
            return TB303_ID
        if kind != "sample":
            return TB303_ID
        fname = desc.get("file") or name
        iid = SAMPLE_PREFIX + fname
        if iid in self.samples:
            return iid
        pdir = os.path.dirname(os.path.abspath(project_path))
        for cand in (os.path.join(INSTRUMENTS_DIR, fname),
                     os.path.join(pdir, "Instruments", fname),
                     os.path.join(pdir, os.pardir, "Instruments", fname),
                     os.path.join(pdir, "instruments", fname),          # older layout
                     os.path.join(pdir, os.pardir, "instruments", fname),
                     desc.get("source") or ""):
            if cand and os.path.isfile(cand):
                try:
                    return self._register_sample(self._copy_into_instruments(cand),
                                                 desc.get("base_freq"),
                                                 origin=desc.get("source") or cand)
                except Exception as e:
                    warnings.append(f"Sample “{fname}” could not be read ({e}): TB-303 used.")
                    return TB303_ID
        warnings.append(f"Sample “{fname}” not found: TB-303 used.\n"
                        f"   (put it in {INSTRUMENTS_DIR} and load the project again)")
        return TB303_ID

    def _apply_top(self, top):
        for k, v in top.get("knobs", {}).items():
            if k in self.kv:
                lo, hi = KNOB_SPEC[k][0], KNOB_SPEC[k][1]
                self.kv[k] = min(hi, max(lo, float(v)))
        self.waveform = top.get("waveform", self.waveform)
        if top.get("scale") in SCALE_MAP:
            self.scale_v.set(top["scale"])
        if top.get("playmode") in PLAYMODES:
            self.playmode_v.set(top["playmode"])
        if top.get("preset") in PRESETS:
            self.preset_v.set(top["preset"])

    def _load_all(self, P, path):
        """Replace the open project with the whole file."""
        was = self.playing
        if was:
            self._stop()
        warnings = []
        self._apply_top(P["top"])
        self.banks = [None if b is None else [dict(s) for s in b] for b in P["banks"]]
        self.bank_settings = [None if s is None else dict(s) for s in P["settings"]]
        self.bank_instr = [self._resolve_instr(d, path, warnings) if d else TB303_ID
                           for d in P["instr"]]
        self._enter_bank(P["cur"])
        self._show_project_name(path)
        if was:
            self._toggle_run()
        self._report(warnings)

    def _import_patterns(self, P, mapping, path):
        """Copy patterns of the file into the open project: mapping = [(src, dst)]."""
        was = self.playing
        if was:
            self._stop()
        warnings = []
        self._freeze_bank()
        for src, dst in mapping:
            b = P["banks"][src]
            self.banks[dst] = ([dict(s) for s in b] if b is not None else
                               [{"note": None, "accent": False, "slide": False} for _ in range(16)])
            s = P["settings"][src]
            self.bank_settings[dst] = dict(s) if s is not None else {
                k: P["top"][k] for k in ("knobs", "waveform", "scale", "playmode")}
            self.bank_instr[dst] = self._resolve_instr(P["instr"][src], path, warnings)
        self._enter_bank(self.cur_bank)          # an import onto this pattern shows now
        if was:
            self._toggle_run()
        self._report(warnings)

    def _report(self, warnings):
        if warnings:
            messagebox.showwarning("Project loaded with warnings", "\n\n".join(warnings))

    def _show_project_name(self, path):
        self._project_path = path
        self._update_window_title()

    def _save_project(self):
        self._freeze_bank()
        rows = [(i, self._summary(self.banks[i], self._instr_label(self.bank_instr[i])))
                for i in range(N_BANKS)]
        dlg = PatternDialog(self.root, "Save project", rows, "save")
        if dlg.result is None:
            return
        include = [src for src, _ in dlg.result]
        last = getattr(self, "_project_path", None)
        path = filedialog.asksaveasfilename(
            title="Enregistrer le projet",
            defaultextension=".tb303", initialdir=PROJECTS_DIR,
            initialfile=os.path.basename(last) if last else "mon_projet.tb303",
            filetypes=[("Projet TB-303", "*.tb303"), ("Tous les fichiers", "*.*")])
        if not path:
            return
        try:
            state = self._project_state(include)
            tmp = path + ".part"                 # never leave a half-written project
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=1, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception as e:
            messagebox.showerror("Cannot save", str(e))
            return
        if not include:
            self._show_project_name(path)

    def _load_project(self):
        path = filedialog.askopenfilename(
            title="Ouvrir un projet",
            initialdir=PROJECTS_DIR,
            filetypes=[("Projet TB-303", "*.tb303"), ("Tous les fichiers", "*.*")])
        if not path:
            return
        try:
            P = self._read_project(path)
        except Exception as e:
            messagebox.showerror("Cannot open", str(e))
            return
        rows = [(i, self._summary(P["banks"][i], self._descriptor_label(P["instr"][i])))
                for i in range(N_BANKS) if P["banks"][i] is not None]
        if not rows:
            messagebox.showinfo("Load project", "This project contains no pattern.")
            return
        self._freeze_bank()
        used = {i for i in range(N_BANKS) if self._pattern_notes(self.banks[i])}
        dlg = PatternDialog(self.root, "Load — " + os.path.basename(path), rows,
                            "load", used)
        if dlg.result is None:
            return
        try:
            if dlg.result:
                self._import_patterns(P, dlg.result, path)
            else:
                self._load_all(P, path)
        except Exception as e:
            messagebox.showerror("Cannot open", str(e))

    # ---------- File > Import pattern from audio... ----------
    IMPORT_SCRIPT = "audio_to_tb303.py"

    def _import_audio(self):
        """Turn a recorded bass line into a pattern (notes, accents, slides, sound).
        audio_to_tb303.py does the work in its own process, so the studio stays
        usable; its messages scroll in the status line."""
        title = "Import pattern from audio"
        if getattr(self, "_import", None) is not None:
            messagebox.showinfo(title, "An import is already running.", parent=self.root)
            return
        script = os.path.join(HERE, self.IMPORT_SCRIPT)
        if not os.path.isfile(script):
            messagebox.showerror(title, f"{self.IMPORT_SCRIPT} is missing from\n{HERE}", parent=self.root)
            return
        path = filedialog.askopenfilename(
            title="Importer un pattern depuis un fichier audio",
            filetypes=[("Audio", " ".join("*" + e for e in self.AUDIO_EXT)),
                       ("Tous les fichiers", "*.*")])
        if not path:
            return
        self._freeze_bank()
        rows = [self._summary(self.banks[i], self._instr_label(self.bank_instr[i]))
                for i in range(N_BANKS)]
        dlg = AudioImportDialog(self.root, os.path.basename(path), rows, self.cur_bank)
        if dlg.result is None:
            return
        target, scale, start, bpm, drums = dlg.result
        fd, tmp = tempfile.mkstemp(prefix="tb303_import_", suffix=".tb303")
        os.close(fd)
        cmd = [sys.executable, "-u", script, path, "-o", tmp, "--scale", scale]
        if drums:
            cmd.append("--mix")
        if start is not None:
            cmd += ["--start", f"{start:g}"]
        if bpm is not None:
            cmd += ["--bpm", f"{bpm:g}"]
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1, cwd=HERE)
        except OSError as e:
            os.remove(tmp)
            messagebox.showerror(title, f"Cannot start the analysis:\n{e}", parent=self.root)
            return
        lines = queue.Queue()

        def read_output():
            for line in proc.stdout:
                lines.put(line.rstrip("\n"))
        threading.Thread(target=read_output, daemon=True).start()
        self._import = {"proc": proc, "queue": lines, "tmp": tmp, "path": path,
                        "target": target, "lines": [], "t0": time.time(), "shown": None}
        self._poll_import()

    def _poll_import(self):
        job = self._import
        while True:
            try:
                line = job["queue"].get_nowait()
            except queue.Empty:
                break
            if line.strip():
                job["lines"].append(line.strip())
        done = job["proc"].poll() is not None
        if not done:
            last = job["lines"][-1] if job["lines"] else "starting"
            # time first: the status line is cut to fit the bar
            text = (f"Import \u2192 pattern {job['target'] + 1} \u00b7 "
                    f"{time.time() - job['t0']:.0f} s \u00b7 {last}")
            if text != job["shown"]:
                job["shown"] = self._busy = text
                self.refresh()
            self.root.after(250, self._poll_import)
            return
        job["proc"].stdout.close()
        time.sleep(0.05)                            # let the reader hand over the last lines
        while not job["queue"].empty():
            line = job["queue"].get_nowait().strip()
            if line:
                job["lines"].append(line)
        self._import, self._busy = None, None
        self.refresh()
        self._finish_import(job)

    def _finish_import(self, job):
        title = "Import pattern from audio"
        name, target, lines = os.path.basename(job["path"]), job["target"], job["lines"]
        try:
            if job["proc"].returncode == 0 and os.path.getsize(job["tmp"]) > 0:
                P = self._read_project(job["tmp"])
                self._import_patterns(P, [(0, target)], job["path"])
                if target != self.cur_bank:
                    self._switch_bank(target)
                found = next((l for l in lines if " BPM | " in l), "")
                notes = next((l for l in lines if l.startswith("Pattern: ")), "")[len("Pattern: "):]
                check = next((l for l in lines if l.startswith("Check the notes")), "")
                drums = any(l.startswith("Drums found") for l in lines)
                messagebox.showinfo(
                    title, f"Pattern {target + 1} now plays {name}.\n\n{notes}\n{found}"
                    + ("\n\nDrums were heard: they were softened before the line was read."
                       if drums else "")
                    + (f"\n\n{check}: the analysis was unsure of them." if check else "")
                    + "\n\nSave the project to keep it.", parent=self.root)
            else:
                why = next((l for l in reversed(lines) if l.startswith("Error:")),
                           "\n".join(lines[-6:]) or "the analysis stopped without a message")
                why = (why.replace("with --bpm", "in the Tempo field of the import window")
                          .replace("with --start", "in the Loop starts at field")
                          .replace("or --mix if drums play along",
                                   "or tick “Drums play along” in the import window"))
                messagebox.showerror(title, f"{name}\n\n{why}", parent=self.root)
        except Exception as e:
            messagebox.showerror(title, f"{name}\n\nThe result could not be read: {e}", parent=self.root)
        finally:
            try:
                os.remove(job["tmp"])
            except OSError:
                pass

    def _clear(self):
        for s in self.steps:
            s.update(note=None, accent=False, slide=False)
        self.sel = 0
        self._changed()


class AudioImportDialog(tk.Toplevel):
    """Where an imported pattern goes, plus the hints the analysis may need.

    After it closes, .result is None if cancelled, otherwise (target pattern
    0-based, scale, loop start in s or None, tempo or None, drums play along)."""

    HINT = ("Works best on an isolated bass line (a single voice) holding at least\n"
            "one full 16-step loop. The analysis takes about a minute; the studio\n"
            "stays usable meanwhile.")

    def __init__(self, master, name, rows, current):
        super().__init__(master)
        self.rows, self.result = rows, None
        self.title("Import pattern from audio")
        self.resizable(False, False)
        self.transient(master)

        body = ttk.Frame(self, padding=14)
        body.grid(sticky="nsew")
        ttk.Label(body, text=name, font=("TkDefaultFont", 10, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(body, text=self.HINT, justify="left", foreground="#555").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(4, 12))

        ttk.Label(body, text="Into pattern").grid(row=2, column=0, sticky="w", pady=3)
        self.choices = [f"{i + 1}   {rows[i]}" for i in range(N_BANKS)]
        empty = [i for i in range(N_BANKS) if rows[i].endswith("empty")]
        first = current if current in empty else (empty[0] if empty else current)
        self.target = tk.StringVar(value=self.choices[first])     # never overwrite by default
        cb = ttk.Combobox(body, textvariable=self.target, values=self.choices,
                          state="readonly", width=34)
        cb.grid(row=2, column=1, columnspan=2, sticky="w", padx=(10, 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self._update())
        self.mark = ttk.Label(body, text="")
        self.mark.grid(row=3, column=1, columnspan=2, sticky="w", padx=(10, 0))

        ttk.Label(body, text="Scale").grid(row=4, column=0, sticky="w", pady=3)
        self.scale = tk.StringVar(value="1/16")
        ttk.Combobox(body, textvariable=self.scale, values=list(SCALE_MAP), state="readonly",
                     width=6).grid(row=4, column=1, sticky="w", padx=(10, 0))
        ttk.Label(body, text="the pattern's SCALE (1/16 suits most lines)", foreground="#555").grid(
            row=4, column=2, sticky="w", padx=(8, 0))

        self.start, self.bpm = tk.StringVar(), tk.StringVar()
        for r, (label, var, unit) in enumerate((("Loop starts at", self.start, "s"),
                                                ("Tempo", self.bpm, "BPM")), start=5):
            ttk.Label(body, text=label).grid(row=r, column=0, sticky="w", pady=3)
            ttk.Entry(body, textvariable=var, width=8).grid(row=r, column=1, sticky="w", padx=(10, 0))
            ttk.Label(body, text=f"{unit}   (empty = found automatically)", foreground="#555").grid(
                row=r, column=2, sticky="w", padx=(8, 0))

        self.drums = tk.BooleanVar(value=False)
        ttk.Checkbutton(body, text="Drums play along", variable=self.drums).grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(6, 3))
        ttk.Label(body, text="softened first (automatic when hi-hats are heard)", foreground="#555").grid(
            row=7, column=2, sticky="w", padx=(8, 0), pady=(6, 3))

        self.msg = ttk.Label(body, text="", foreground="#b03a1a")
        self.msg.grid(row=8, column=0, columnspan=3, sticky="w", pady=(8, 0))
        foot = ttk.Frame(body)
        foot.grid(row=9, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(foot, text="Cancel", command=self.destroy).pack(side="right")
        self.ok = ttk.Button(foot, text="Import", command=self._accept)
        self.ok.pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._accept())
        self._update()
        self.update_idletasks()
        try:                                     # centre over the studio window
            x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
            y = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 3
            self.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass
        self.grab_set()
        self.ok.focus_set()
        self.wait_window()

    def _index(self):
        return self.choices.index(self.target.get())

    def _update(self):
        empty = self.rows[self._index()].endswith("empty")
        self.mark.configure(text="empty pattern" if empty else "replaces this pattern",
                            foreground="#3c7a3c" if empty else "#b8730a")

    @staticmethod
    def _number(text, low, high, what):
        text = text.strip().replace(",", ".")
        if not text:
            return None
        try:
            v = float(text)
        except ValueError:
            raise ValueError(f"{what}: “{text}” is not a number.")
        if not low <= v <= high:
            raise ValueError(f"{what} must be between {low:g} and {high:g}.")
        return v

    def _accept(self):
        try:
            start = self._number(self.start.get(), 0, 3600, "Loop start")
            bpm = self._number(self.bpm.get(), 60, 200, "Tempo")
        except ValueError as e:
            self.msg.configure(text=str(e))
            return
        self.result = (self._index(), self.scale.get(), start, bpm, self.drums.get())
        self.destroy()


class PatternDialog(tk.Toplevel):
    """Modal list of patterns, one tick box each.

    mode "save": rows are the 8 patterns of the open project.
    mode "load": rows are the patterns found in a file, each with a target slot.

    After it closes, .result is None if cancelled, otherwise the list of
    (source, target) pairs that were ticked (0-based) -- an EMPTY list meaning
    nothing was ticked, i.e. "everything".
    """

    HINT = {
        "save": "Tick the patterns to save. Nothing ticked = save all 8.\n"
                "Each pattern keeps its number, its sound and its instrument.",
        "load": "Tick the patterns to import into the open project, and choose\n"
                "where each one goes. Nothing ticked = load the whole project,\n"
                "replacing the one that is open.",
    }

    def __init__(self, master, title, rows, mode, used_slots=()):
        super().__init__(master)
        self.mode, self.rows, self.used = mode, rows, set(used_slots)
        self.result = None
        self.title(title)
        self.resizable(False, False)
        self.transient(master)

        body = ttk.Frame(self, padding=14)
        body.grid(sticky="nsew")
        ttk.Label(body, text=self.HINT[mode], justify="left").grid(
            row=0, column=0, columnspan=5, sticky="w", pady=(0, 10))

        self.ticks, self.targets, self.marks = [], [], []
        slots = [str(i + 1) for i in range(N_BANKS)]
        for r, (idx, summary) in enumerate(rows, start=1):
            v = tk.BooleanVar(value=False)
            ttk.Checkbutton(body, text=f"Pattern {idx + 1}", variable=v,
                            command=self._update).grid(row=r, column=0, sticky="w", pady=2)
            ttk.Label(body, text=summary, foreground="#555").grid(
                row=r, column=1, sticky="w", padx=(10, 16))
            self.ticks.append(v)
            if mode == "load":
                ttk.Label(body, text="→ pattern").grid(row=r, column=2, sticky="e")
                t = tk.StringVar(value=str(idx + 1))
                cb = ttk.Combobox(body, textvariable=t, values=slots, width=3, state="readonly")
                cb.grid(row=r, column=3, padx=(4, 8))
                cb.bind("<<ComboboxSelected>>", lambda e: self._update())
                self.targets.append(t)
                m = ttk.Label(body, text="", width=22)
                m.grid(row=r, column=4, sticky="w")
                self.marks.append(m)

        quick = ttk.Frame(body)
        quick.grid(row=len(rows) + 1, column=0, columnspan=5, sticky="w", pady=(8, 0))
        ttk.Button(quick, text="Tick all", command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(quick, text="Clear", command=lambda: self._set_all(False)).pack(side="left", padx=6)

        self.msg = ttk.Label(body, text="", foreground="#b03a1a")
        self.msg.grid(row=len(rows) + 2, column=0, columnspan=5, sticky="w", pady=(8, 0))

        foot = ttk.Frame(body)
        foot.grid(row=len(rows) + 3, column=0, columnspan=5, sticky="e", pady=(10, 0))
        ttk.Button(foot, text="Cancel", command=self.destroy).pack(side="right")
        self.ok = ttk.Button(foot, text="", command=self._accept)
        self.ok.pack(side="right", padx=(0, 8))

        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Return>", lambda e: self._accept())
        self._update()
        self.update_idletasks()
        try:                                     # centre over the studio window
            x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
            y = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 3
            self.geometry(f"+{max(0, x)}+{max(0, y)}")
        except Exception:
            pass
        self.grab_set()
        self.ok.focus_set()
        self.wait_window()

    def _set_all(self, on):
        for v in self.ticks:
            v.set(on)
        self._update()

    def _pairs(self):
        out = []
        for k, v in enumerate(self.ticks):
            if v.get():
                src = self.rows[k][0]
                dst = int(self.targets[k].get()) - 1 if self.mode == "load" else src
                out.append((src, dst))
        return out

    def _update(self):
        pairs = self._pairs()
        n = len(pairs)
        problem = ""
        if self.mode == "save":
            label = "Save all 8 patterns…" if n == 0 else \
                f"Save {n} pattern{'s' if n > 1 else ''}…"
        else:
            label = "Load all (replaces the open project)" if n == 0 else \
                f"Import {n} pattern{'s' if n > 1 else ''}"
            dsts = [d for _, d in pairs]
            for k, v in enumerate(self.ticks):
                d = int(self.targets[k].get()) - 1
                if not v.get():
                    self.marks[k].configure(text="")
                elif dsts.count(d) > 1:
                    self.marks[k].configure(text="same target!", foreground="#b03a1a")
                elif d in self.used:
                    self.marks[k].configure(text=f"replaces pattern {d + 1}", foreground="#b8730a")
                else:
                    self.marks[k].configure(text="empty slot", foreground="#3c7a3c")
            if len(set(dsts)) != len(dsts):
                problem = "Two patterns are sent to the same place: change one target."
        self.msg.configure(text=problem)
        self.ok.configure(text=label, state="disabled" if problem else "normal")

    def _accept(self):
        if str(self.ok.cget("state")) == "disabled":
            return
        self.result = self._pairs()
        self.destroy()


LOG_PATH = None                         # set when the studio writes to a log file


def _log_to_file_without_terminal():
    """Started from the desktop icon there is no terminal: keep what the studio
    prints (MIDI, errors) in TB303-Studio/tb303_studio.log, rewritten each run."""
    global LOG_PATH
    try:
        if sys.stdout is not None and sys.stdout.isatty():
            return
    except (AttributeError, ValueError):
        pass
    try:
        path = os.path.join(ROOT, "tb303_studio.log")
        log = open(path, "w", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
        LOG_PATH = path
        print(time.strftime("TB-303 Studio started %Y-%m-%d %H:%M:%S"), "-", sys.executable)
    except OSError:
        pass


def _tools_next_to_python_on_path():
    """From the icon a conda env is not activated: put its bin/ on PATH, as the
    terminal does, so ffmpeg/ffprobe/ffplay installed with conda are found."""
    bindir = os.path.dirname(sys.executable)
    path = os.environ.get("PATH", "")
    if bindir and bindir not in path.split(os.pathsep):
        os.environ["PATH"] = bindir + (os.pathsep + path if path else "")


def _report_stalls(root, after=8.0):
    """A freeze leaves no error message. When the window has not answered for `after`
    seconds, print where each thread is (in the terminal, or in tb303_studio.log when
    started from the icon): it shows what the studio waits for. kill -USR1 <pid>
    prints the same at any time."""
    import faulthandler
    import signal
    beat = [time.monotonic()]

    def tick():
        beat[0] = time.monotonic()
        root.after(250, tick)

    def watch():
        told = False
        while True:
            time.sleep(1)
            silent = time.monotonic() - beat[0]
            if silent > after and not told:
                told = True
                try:
                    print(f"\nTB-303 Studio has not answered for {silent:.0f} s. "
                          "Where each thread is:", file=sys.stderr, flush=True)
                    faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
                except (AttributeError, OSError, ValueError):
                    pass
            elif silent < 1:
                told = False

    tick()
    threading.Thread(target=watch, name="stall report", daemon=True).start()
    if hasattr(signal, "SIGUSR1"):
        try:
            faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True)
        except (AttributeError, OSError, RuntimeError, ValueError):
            pass


def main():
    _log_to_file_without_terminal()
    _tools_next_to_python_on_path()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    image = args[0] if args else _find_skin()
    root = tk.Tk(className=WM_CLASS)
    if os.path.exists(ICON_PATH):
        try:
            root._icon = tk.PhotoImage(file=ICON_PATH)
            root.iconphoto(True, root._icon)
        except tk.TclError:
            pass
    if not os.path.exists(image):
        root.withdraw()
        messagebox.showerror("TB-303 Studio", f"Skin image not found:\n{image}")
        raise SystemExit(f"Image introuvable : {image}")
    try:
        app = SkinStudio(root, image)
    except Exception as e:
        import traceback
        traceback.print_exc()
        root.withdraw()
        where = f"Details in {LOG_PATH}" if LOG_PATH else "Details in the terminal."
        messagebox.showerror("TB-303 Studio could not start", f"{type(e).__name__}: {e}\n\n{where}")
        raise

    # --- MIDI control surface (optional): knobs, pads and keys from a
    # controller such as the Akai MPK mini Plus. Missing hardware, a missing
    # mido/python-rtmidi, or no port at all must never stop the studio from
    # opening: the mouse still drives everything. Launch with --nomidi to skip.
    app.midi = None
    if "--nomidi" not in sys.argv:
        try:
            import midi_in
            app.midi = midi_in.attach(app)
        except (Exception, SystemExit) as e:        # midi_in exits when mido is missing
            print(f"MIDI off ({e}) — mouse only")

    def _on_close():
        if not app._confirm_close_recording():
            return
        if app.midi is not None:
            app.midi.close()
        app.close()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_close)
    _report_stalls(root)
    root.mainloop()


if __name__ == "__main__":
    main()
