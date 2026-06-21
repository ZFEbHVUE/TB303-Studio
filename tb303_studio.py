#!/usr/bin/env python3
"""
tb303_studio.py — GUI "skinnee" : habillage = image (tb303_skin.png),
controles fonctionnels superposes aux coordonnees relevees sur tes reperes rouges.

Va avec tb303.py et tb303_skin.png (meme dossier).
numpy + Pillow requis ; pygame optionnel (lecture temps reel).
Lancement : python tb303_studio.py
"""
import sys, os, json, math
import numpy as np
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tb303 import TB303, DEMO_PATTERN, parse_step
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

# Carte des coordonnees (pixels image native) relevee sur les reperes rouges
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
        "save": [455, 728, 63, 16], "clear": [629, 729, 46, 17], "demo": [783, 728, 43, 17],
    },
    "piano": [259, 394, 986, 545],
    "cells": {"cx": [401, 474, 548, 622, 696, 769, 843, 917, 993, 1068, 1142, 1217,
                     1292, 1367, 1447, 1525], "cy": 602, "hw": 32, "hh": 28},
    "status": [880, 728], "show_values": True,
    "ink": "#241a0a", "needle": "#ffcf6b", "accent_fg": "#c0451f", "slide_fg": "#3f7fa0",
    "val_fg": "#f0d9a0", "sel": "#ffcf6b",
}


class SkinStudio:
    SR = 44100

    def __init__(self, root, image_path):
        if not _HAS_PIL:
            raise SystemExit("Pillow requis : pip install pillow")
        self.root = root
        self.tb = TB303(self.SR)
        self.M = SKIN_MAP
        self.img = Image.open(image_path).convert("RGB")
        self.IW, self.IH = self.img.size
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        self.scale = min(1.0, (sw - 30) / self.IW, (sh - 90) / self.IH)
        disp = (self.img.resize((int(self.IW * self.scale), int(self.IH * self.scale)),
                                Image.LANCZOS) if self.scale < 1 else self.img)
        self.bg = ImageTk.PhotoImage(disp)
        root.title("TB-303 Studio — " + os.path.basename(image_path))
        root.resizable(False, False)
        self.cv = tk.Canvas(root, width=disp.width, height=disp.height, highlightthickness=0)
        self.cv.pack()
        self.cv.create_image(0, 0, anchor="nw", image=self.bg)

        self.kv = {k: KNOB_SPEC[k][2] for k in KNOB_SPEC}
        self.waveform = "square"
        self.scale_v = tk.StringVar(value="1/16")
        self.playmode_v = tk.StringVar(value="Forward")
        self.preset_v = tk.StringVar(value="Classic Bass")
        self.steps = []
        self._load_pattern(DEMO_PATTERN)
        self.banks = [None] * 8
        self.banks[0] = [dict(s) for s in self.steps]
        self.cur_bank = 0
        self.sel = 0
        self.playing = False
        self._drag = None
        self.audio_ok = self._init_audio()
        self._presample_colors()
        self._make_combos()
        self.cv.bind("<Button-1>", self._click)
        self.cv.bind("<B1-Motion>", self._motion)
        self.cv.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag", None))
        self.cv.bind("<MouseWheel>", self._wheel)
        self.cv.bind("<Button-4>", self._wheel)
        self.cv.bind("<Button-5>", self._wheel)
        # --- menu Fichier : projet .tb303 (etat complet) + export WAV ---
        menubar = tk.Menu(root)
        filem = tk.Menu(menubar, tearoff=0)
        filem.add_command(label="Ouvrir projet\u2026   (Ctrl+O)", command=self._load_project)
        filem.add_command(label="Sauvegarder projet\u2026   (Ctrl+S)", command=self._save_project)
        filem.add_separator()
        filem.add_command(label="Exporter WAV\u2026", command=self._save)
        menubar.add_cascade(label="Fichier", menu=filem)
        root.config(menu=menubar)
        root.bind("<Control-s>", lambda e: self._save_project())
        root.bind("<Control-o>", lambda e: self._load_project())
        self._apply_preset("Classic Bass")
        self.refresh()

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
        if not _HAS_PYGAME:
            self.audio_err = "pygame absent — pip install pygame"
            return False
        # WSL/WSLg : router le son vers PulseAudio (sinon aucun peripherique audio)
        if os.path.exists("/mnt/wslg/PulseServer"):
            os.environ.setdefault("SDL_AUDIODRIVER", "pulseaudio")
            os.environ["PULSE_SERVER"] = "unix:/mnt/wslg/PulseServer"  # ecrase une valeur stale
        try:
            pygame.mixer.quit()
            pygame.mixer.init(frequency=self.SR, size=-16, channels=2)
            return True
        except Exception as e:
            self.audio_err = f"audio KO ({e})"
            return False

    def _make_combos(self):
        try:
            st = ttk.Style()
            st.theme_use("clam")
            st.configure("Skin.TCombobox", fieldbackground="#2a1c0e", background="#5a4326",
                         foreground="#f0d9a0", arrowcolor="#f0d9a0")
            st.map("Skin.TCombobox", fieldbackground=[("readonly", "#2a1c0e")],
                   foreground=[("readonly", "#f0d9a0")])
        except Exception:
            pass
        for name, var, vals in [("scale", self.scale_v, list(SCALE_MAP)),
                                ("playmode", self.playmode_v, list(PLAYMODES)),
                                ("preset", self.preset_v, list(PRESETS))]:
            cx, cy, w = self.M["combos"][name]
            cb = ttk.Combobox(self.cv, textvariable=var, values=vals, state="readonly",
                              style="Skin.TCombobox", width=max(6, int(self.S(w) / 8)),
                              font=("Georgia", 9))
            self.cv.create_window(self.S(cx), self.S(cy), window=cb)
            if name == "preset":
                cb.bind("<<ComboboxSelected>>", lambda e: self._apply_preset(self.preset_v.get()))
            else:
                cb.bind("<<ComboboxSelected>>", lambda e: self._changed())

    def refresh(self):
        self.cv.delete("dyn")
        S = self.S
        for k, (cx, cy, r, vx, vy) in self.M["knobs"].items():
            vmin, vmax, _, fmt = KNOB_SPEC[k]
            frac = (self.kv[k] - vmin) / (vmax - vmin)
            ang = math.radians(135 + frac * 270)
            self.cv.create_line(S(cx), S(cy), S(cx + (r - 6) * math.cos(ang)),
                                S(cy + (r - 6) * math.sin(ang)), fill=self.M["needle"],
                                width=max(2, int(S(3))), capstyle="round", tags="dyn")
            self.cv.create_oval(S(cx) - 3, S(cy) - 3, S(cx) + 3, S(cy) + 3,
                                fill="#1a1206", outline=self.M["needle"], tags="dyn")
            if self.M.get("show_values"):
                self.cv.create_rectangle(S(vx) - S(22), S(vy) - S(9), S(vx) + S(22), S(vy) + S(9),
                                         fill=self.valbg[k], outline="", tags="dyn")
                self.cv.create_text(S(vx), S(vy), text=fmt.format(self.kv[k]), fill=self.M["val_fg"],
                                    font=("Georgia", max(7, int(S(11))), "bold"), tags="dyn")
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
                                font=("Georgia", max(8, int(S(13))), "bold"), tags="dyn")
            if sub:
                self.cv.create_text(S(cx), S(C["cy"]) + S(11), text=sub, fill=col,
                                    font=("Georgia", max(7, int(S(10))), "bold"), tags="dyn")
            if i == self.sel:
                self.cv.create_rectangle(S(cx) - S(C["hw"]), S(C["cy"]) - S(C["hh"]),
                                         S(cx) + S(C["hw"]), S(C["cy"]) + S(C["hh"]),
                                         outline=self.M["sel"], width=3, tags="dyn")
        msg = ("\u25b6 lecture" if self.playing else (self.audio_err if not self.audio_ok else "Pret"))
        self.cv.create_text(S(self.M["status"][0]), S(self.M["status"][1]), anchor="w",
                            text=msg, fill="#d8c08a", font=("Georgia", max(8, int(S(11)))), tags="dyn")

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
            self._piano_hit(x, px0, px1)
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
        self._changed()

    def _wheel(self, e):
        x, y = self._to_img(e)
        k = self._knob_at(x, y)
        if not k:
            return
        vmin, vmax = KNOB_SPEC[k][0], KNOB_SPEC[k][1]
        step = (vmax - vmin) / 40.0
        up = getattr(e, "num", None) == 4 or getattr(e, "delta", 0) > 0
        self.kv[k] = min(vmax, max(vmin, self.kv[k] + (step if up else -step)))
        self._changed()

    def _piano_hit(self, x, px0, px1):
        whites = [(w, o) for o in (1, 2, 3) for w in ["C", "D", "E", "F", "G", "A", "B"]]
        idx = min(len(whites) - 1, max(0, int((x - px0) / (px1 - px0) * len(whites))))
        self._set_note(f"{whites[idx][0]}{whites[idx][1]}")

    def _button(self, name):
        {"run": self._toggle_run, "stop": self._stop,
         "accent": lambda: self._toggle_step("accent"), "slide": lambda: self._toggle_step("slide"),
         "oct_down": lambda: self._octave(-1), "oct_up": lambda: self._octave(1),
         "rest": lambda: self._set_note(None), "save": self._save, "clear": self._clear,
         "demo": lambda: (self._load_pattern(DEMO_PATTERN), setattr(self, "sel", 0), self._changed())}[name]()

    def _apply_preset(self, name):
        p = PRESETS.get(name)
        if not p:
            return
        self.waveform = p["waveform"]
        for k in ("cutoff", "resonance", "env_mod", "decay", "accent", "distortion", "shuffle"):
            self.kv[k] = p[k]
        self._changed()

    def _switch_bank(self, b):
        self.banks[self.cur_bank] = [dict(s) for s in self.steps]
        self.cur_bank = b
        if self.banks[b] is None:
            self.banks[b] = [{"note": None, "accent": False, "slide": False} for _ in range(16)]
        self.steps = [dict(s) for s in self.banks[b]]
        self.sel = 0
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
        if not self.audio_ok or not note:
            return
        try:
            p = self._params()
            p.update(bpm=80, subdiv=1, swing=0.0, play_mode="forward")
            a = self.tb.render([{"note": note, "accent": False, "slide": False}], repeats=1, **p)
            a = np.clip(a * self.kv["volume"] / 0.9, -1, 1)
            self._ps = pygame.sndarray.make_sound(np.ascontiguousarray((a * 0.9 * 32767).astype(np.int16)))
            self._ps.play()
        except Exception:
            pass

    def _changed(self):
        self.refresh()
        if self.playing and self.audio_ok:
            self._play_loop()

    def _play_loop(self):
        try:
            a = self._render(1)
            d = np.ascontiguousarray((np.clip(a, -1, 1) * 32767).astype(np.int16))
            pygame.mixer.stop()
            self._snd = pygame.sndarray.make_sound(d)
            self._snd.play(loops=-1)
        except Exception as e:
            self.playing = False
            self.audio_err = f"RUN KO ({e})"
            self.refresh()

    def _toggle_run(self):
        if not self.audio_ok:
            messagebox.showinfo(
                "Audio indisponible",
                "Le moteur audio n'est pas actif : " + (self.audio_err or "pygame manquant") + ".\n\n"
                "RUN n'a donc rien a jouer (le bouton fonctionne, mais il n'y a pas de son).\n\n"
                "Dans le terminal ou tu lances le script :\n"
                "    pip install pygame\n"
                "puis relance.  (SAVE WAV fonctionne sans pygame.)")
            return
        if self.playing:
            self._stop()
        else:
            self.playing = True
            self._play_loop()
            self.refresh()

    def _stop(self):
        self.playing = False
        if self.audio_ok:
            pygame.mixer.stop()
        self.refresh()

    def _save(self):
        path = filedialog.asksaveasfilename(defaultextension=".wav",
                                            filetypes=[("WAV", "*.wav")], initialfile="tb303.wav")
        if path:
            self.tb.write_wav(self._render(4), path)

    # ---------- projet .tb303 (etat complet, rappelable) ----------
    def _project_state(self):
        self.banks[self.cur_bank] = [dict(s) for s in self.steps]   # fige la banque courante
        return {
            "format": "tb303-studio", "version": 1,
            "knobs": {k: round(float(v), 4) for k, v in self.kv.items()},
            "waveform": self.waveform,
            "scale": self.scale_v.get(),
            "playmode": self.playmode_v.get(),
            "preset": self.preset_v.get(),
            "cur_bank": self.cur_bank,
            "banks": [None if b is None else [dict(s) for s in b] for b in self.banks],
        }

    def _apply_project(self, st):
        for k in self.kv:
            if k in st.get("knobs", {}):
                vmin, vmax = KNOB_SPEC[k][0], KNOB_SPEC[k][1]
                self.kv[k] = min(vmax, max(vmin, float(st["knobs"][k])))
        self.waveform = st.get("waveform", self.waveform)
        self.scale_v.set(st.get("scale", self.scale_v.get()))
        self.playmode_v.set(st.get("playmode", self.playmode_v.get()))
        self.preset_v.set(st.get("preset", self.preset_v.get()))
        banks = st.get("banks")
        if banks and len(banks) == 8:
            self.banks = [None if b is None else
                          [{"note": s.get("note"), "accent": bool(s.get("accent")),
                            "slide": bool(s.get("slide"))} for s in b] for b in banks]
        self.cur_bank = int(st.get("cur_bank", 0)) % 8
        if self.banks[self.cur_bank] is None:
            self.banks[self.cur_bank] = [{"note": None, "accent": False, "slide": False}
                                         for _ in range(16)]
        self.steps = [dict(s) for s in self.banks[self.cur_bank]]
        self.sel = 0
        self.refresh()
        if self.playing and self.audio_ok:
            self._play_loop()

    def _save_project(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".tb303", filetypes=[("Projet TB-303", "*.tb303"), ("Tous", "*.*")],
            initialfile="mon_pattern.tb303")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._project_state(), f, indent=1, ensure_ascii=False)
        except Exception as e:
            messagebox.showerror("Sauvegarde impossible", str(e))

    def _load_project(self):
        path = filedialog.askopenfilename(
            filetypes=[("Projet TB-303", "*.tb303"), ("Tous", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                st = json.load(f)
            if st.get("format") != "tb303-studio":
                raise ValueError("Ce fichier n'est pas un projet TB-303.")
            self._apply_project(st)
        except Exception as e:
            messagebox.showerror("Ouverture impossible", str(e))

    def _clear(self):
        for s in self.steps:
            s.update(note=None, accent=False, slide=False)
        self.sel = 0
        self._changed()


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    image = args[0] if args else os.path.join(here, "tb303_skin.png")
    if not os.path.exists(image):
        raise SystemExit(f"Image introuvable : {image}")
    root = tk.Tk()
    SkinStudio(root, image)
    root.mainloop()


if __name__ == "__main__":
    main()
