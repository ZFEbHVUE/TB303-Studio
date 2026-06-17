#!/usr/bin/env python3
"""
tb303_studio.py — GUI style TB-303 pour le moteur tb303.py.

Knobs : Tuning, Cut Off, Resonance, Env Mod, Decay, Accent | Tempo, Distortion,
Volume, Shuffle (swing). Selecteurs Scale (subdivision) et Play Mode.
Clavier piano + colonnes Accent/Slide/Octave. 16 pas. 8 banques de patterns.

Necessite tb303.py (meme dossier), numpy, pygame (optionnel : lecture).
Lancement : python tb303_studio.py
"""

import math
import numpy as np
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from tb303 import TB303, DEMO_PATTERN, parse_step

try:
    import pygame
    _HAS_PYGAME = True
except Exception:
    _HAS_PYGAME = False

BG = "#c9ccce"
PANEL = "#bfc3c6"
DARK = "#2b2b2b"
ACID = "#ff8c1a"
RED = "#cc2222"
BLUE = "#1e6fce"
SEL = "#ffd24d"
BANK_ON = "#ff8c1a"

SCALE_MAP = {"1/8": 2, "1/8T": 3, "1/16": 4, "1/16T": 6, "1/32": 8}
PLAYMODES = {"Forward": "forward", "Reverse": "reverse", "Fwd&Rev": "fwd_rev",
             "Invert": "invert", "Random": "random"}


class Knob(tk.Canvas):
    def __init__(self, master, label, vmin, vmax, value, command=None,
                 fmt="{:.2f}", size=52):
        super().__init__(master, width=size, height=size + 26, bg=BG, highlightthickness=0)
        self.label, self.vmin, self.vmax = label, vmin, vmax
        self.value, self.command, self.fmt, self.size = value, command, fmt, size
        self._default, self._last_y = value, 0
        self.bind("<Button-1>", lambda e: setattr(self, "_last_y", e.y))
        self.bind("<B1-Motion>", self._drag)
        self.bind("<Double-Button-1>", lambda e: self._set(self._default))
        self._draw()

    def _draw(self):
        self.delete("all")
        s = self.size
        c = s / 2
        r = s / 2 - 5
        self.create_oval(c - r, c - r, c + r, c + r, fill=DARK, outline="#000", width=2)
        frac = (self.value - self.vmin) / (self.vmax - self.vmin)
        a = math.radians(135 + frac * 270)
        self.create_line(c, c, c + (r - 4) * math.cos(a), c + (r - 4) * math.sin(a),
                         fill=ACID, width=3, capstyle="round")
        self.create_text(c, s + 6, text=self.label, font=("TkDefaultFont", 7, "bold"))
        self.create_text(c, s + 17, text=self.fmt.format(self.value), font=("TkDefaultFont", 7))

    def _drag(self, e):
        dy = e.y - self._last_y
        self._last_y = e.y
        self._set(self.value - dy * (self.vmax - self.vmin) / 150.0)

    def _set(self, v):
        self.value = min(self.vmax, max(self.vmin, v))
        self._draw()
        if self.command:
            self.command(self.value)

    def get(self):
        return self.value


class Piano(tk.Canvas):
    BLACK_AFTER = {0: "C#", 1: "D#", 3: "F#", 4: "G#", 5: "A#"}

    def __init__(self, master, octaves=(1, 2, 3), command=None, kw=21, kh=82):
        self.kw, self.kh, self.command = kw, kh, command
        self.whites = [(w, o) for o in octaves for w in ["C", "D", "E", "F", "G", "A", "B"]]
        super().__init__(master, width=len(self.whites) * kw, height=kh,
                         bg=BG, highlightthickness=0)
        self._rects = []
        self._draw()
        self.bind("<Button-1>", self._click)

    def _draw(self):
        self.delete("all")
        self._rects = []
        kw, kh = self.kw, self.kh
        for i, (n, o) in enumerate(self.whites):
            x0 = i * kw
            self.create_rectangle(x0, 0, x0 + kw, kh, fill="#f4f4f4", outline="#555")
            self._rects.append((x0, x0 + kw, 0, kh, f"{n}{o}", False))
        for idx in range(len(self.whites) - 1):
            local = idx % 7
            if local in self.BLACK_AFTER:
                o = self.whites[idx][1]
                bw = kw * 0.62
                x = (idx + 1) * kw - bw / 2
                self.create_rectangle(x, 0, x + bw, kh * 0.6, fill=DARK, outline="#000")
                self._rects.append((x, x + bw, 0, kh * 0.6, f"{self.BLACK_AFTER[local]}{o}", True))

    def _click(self, e):
        for x0, x1, y0, y1, name, black in self._rects:
            if black and x0 <= e.x <= x1 and y0 <= e.y <= y1:
                return self.command and self.command(name)
        for x0, x1, y0, y1, name, black in self._rects:
            if not black and x0 <= e.x <= x1 and y0 <= e.y <= y1:
                return self.command and self.command(name)


class TB303Studio:
    SR = 44100

    def __init__(self, root):
        self.root = root
        self.tb = TB303(self.SR)
        self.playing = False
        self.sel = 0
        self.cur_bank = 0
        self.banks = [None] * 8
        self.audio_ok = self._init_audio()
        self.steps = []
        self._load_pattern(DEMO_PATTERN)
        self.banks[0] = [dict(s) for s in self.steps]
        root.title("TB-303 Studio")
        root.configure(bg=BG)
        root.resizable(False, False)
        self._build()
        self._refresh_strip()
        self._highlight_bank()

    def _init_audio(self):
        if not _HAS_PYGAME:
            return False
        try:
            pygame.mixer.quit()
            pygame.mixer.init(frequency=self.SR, size=-16, channels=2)
            return True
        except Exception:
            return False

    def _load_pattern(self, pattern):
        self.steps = []
        for s in pattern[:16]:
            d = parse_step(s)
            self.steps.append({"note": d["note"], "accent": d["accent"], "slide": d["slide"]})
        while len(self.steps) < 16:
            self.steps.append({"note": None, "accent": False, "slide": False})

    # ---------------- UI ----------------
    def _build(self):
        top = tk.Frame(self.root, bg=BG, padx=10, pady=8)
        top.grid(row=0, column=0, sticky="we")
        self.waveform = tk.StringVar(value="saw")
        wf = tk.Frame(top, bg=BG)
        wf.grid(row=0, column=0, padx=(0, 8))
        tk.Label(wf, text="WAVEFORM", bg=BG, font=("TkDefaultFont", 7, "bold")).pack()
        for txt, val in [("\u25fb saw", "saw"), ("\u2293 sqr", "square")]:
            ttk.Radiobutton(wf, text=txt, value=val, variable=self.waveform,
                            command=self._changed).pack(anchor="w")

        self.knobs = {}
        row1 = [("tuning", "TUNING", 400, 480, 440, "{:.0f}"),
                ("cutoff", "CUT OFF", 0, 1, 0.30, "{:.2f}"),
                ("resonance", "RESONANCE", 0, 1, 0.82, "{:.2f}"),
                ("env_mod", "ENV MOD", 0, 1, 0.62, "{:.2f}"),
                ("decay", "DECAY", 0, 1, 0.50, "{:.2f}"),
                ("accent", "ACCENT", 0, 1, 0.65, "{:.2f}")]
        for i, (k, l, lo, hi, v, f) in enumerate(row1):
            kn = Knob(top, l, lo, hi, v, command=lambda _v: self._changed(), fmt=f)
            kn.grid(row=0, column=1 + i, padx=3)
            self.knobs[k] = kn
        tk.Label(top, text="BASS  LINE", bg=BG, fg=DARK,
                 font=("TkDefaultFont", 14, "bold")).grid(row=0, column=8, padx=10)

        # rangee 2 : knobs + selecteurs
        mid = tk.Frame(self.root, bg=BG, padx=10, pady=2)
        mid.grid(row=1, column=0, sticky="we")
        row2 = [("bpm", "TEMPO", 60, 200, 130, "{:.0f}"),
                ("distortion", "DIST", 0, 1, 0.25, "{:.2f}"),
                ("volume", "VOLUME", 0, 1, 0.9, "{:.2f}"),
                ("shuffle", "SHUFFLE", 0, 0.66, 0.0, "{:.2f}")]
        for i, (k, l, lo, hi, v, f) in enumerate(row2):
            kn = Knob(mid, l, lo, hi, v, command=lambda _v: self._changed(), fmt=f)
            kn.grid(row=0, column=i, padx=3)
            self.knobs[k] = kn

        sf = tk.Frame(mid, bg=BG)
        sf.grid(row=0, column=4, padx=12)
        tk.Label(sf, text="SCALE", bg=BG, font=("TkDefaultFont", 7, "bold")).grid(row=0, column=0)
        self.scale = tk.StringVar(value="1/16")
        ttk.Combobox(sf, textvariable=self.scale, values=list(SCALE_MAP),
                     state="readonly", width=6).grid(row=1, column=0, pady=1)
        tk.Label(sf, text="PLAY MODE", bg=BG, font=("TkDefaultFont", 7, "bold")).grid(row=0, column=1)
        self.playmode = tk.StringVar(value="Forward")
        ttk.Combobox(sf, textvariable=self.playmode, values=list(PLAYMODES),
                     state="readonly", width=8).grid(row=1, column=1, padx=4)
        self.scale.trace_add("write", lambda *a: self._changed())
        self.playmode.trace_add("write", lambda *a: self._changed())

        # banques 1-8
        bf = tk.Frame(mid, bg=BG)
        bf.grid(row=0, column=5, padx=10)
        tk.Label(bf, text="PATTERN", bg=BG, font=("TkDefaultFont", 7, "bold")).grid(
            row=0, column=0, columnspan=8)
        self.bank_btns = []
        for i in range(8):
            b = tk.Button(bf, text=str(i + 1), width=2,
                          command=lambda idx=i: self._switch_bank(idx))
            b.grid(row=1, column=i, padx=1)
            self.bank_btns.append(b)

        # bas : transport | clavier | colonnes
        bottom = tk.Frame(self.root, bg=PANEL, padx=10, pady=8)
        bottom.grid(row=2, column=0, sticky="we")
        tr = tk.Frame(bottom, bg=PANEL)
        tr.grid(row=0, column=0, rowspan=2, padx=(0, 12), sticky="n")
        self.run_btn = tk.Button(tr, text="\u25b6\nRUN", width=6, height=2, bg="#7a7",
                                 command=self.toggle_run)
        self.run_btn.pack(pady=2)
        tk.Button(tr, text="\u25a0\nSTOP", width=6, height=2, bg="#c77",
                  command=self.stop).pack(pady=2)

        center = tk.Frame(bottom, bg=PANEL)
        center.grid(row=0, column=1)
        self.piano = Piano(center, octaves=(1, 2, 3), command=self._set_note)
        self.piano.pack()

        cols = tk.Frame(bottom, bg=PANEL)
        cols.grid(row=0, column=2, padx=(12, 0))
        tk.Button(cols, text="ACCENT", bg="#e7b3b3", width=7,
                  command=lambda: self._toggle("accent")).grid(row=0, column=0, padx=2)
        tk.Button(cols, text="SLIDE", bg="#b3c8e7", width=7,
                  command=lambda: self._toggle("slide")).grid(row=0, column=1, padx=2)
        tk.Button(cols, text="OCT \u2193", width=5,
                  command=lambda: self._octave(-1)).grid(row=0, column=2, padx=2)
        tk.Button(cols, text="OCT \u2191", width=5,
                  command=lambda: self._octave(+1)).grid(row=0, column=3, padx=2)
        tk.Button(cols, text="REST", width=6,
                  command=lambda: self._set_note(None)).grid(row=0, column=4, padx=8)

        strip = tk.Frame(bottom, bg=PANEL)
        strip.grid(row=1, column=1, columnspan=2, pady=(8, 0))
        self.cells = []
        for i in range(16):
            c = tk.Label(strip, width=5, height=2, relief="ridge", bd=1,
                         bg="#e9e9e9", font=("TkDefaultFont", 7))
            c.grid(row=0, column=i, padx=1)
            c.bind("<Button-1>", lambda e, idx=i: self._select(idx))
            self.cells.append(c)

        foot = tk.Frame(self.root, bg=BG, padx=10, pady=6)
        foot.grid(row=3, column=0, sticky="we")
        ttk.Button(foot, text="\U0001f4be Save WAV", command=self.save).grid(row=0, column=0, padx=3)
        ttk.Button(foot, text="Clear", command=self.clear).grid(row=0, column=1, padx=3)
        ttk.Button(foot, text="Demo", command=self.load_demo).grid(row=0, column=2, padx=3)
        self.status = tk.StringVar()
        tk.Label(foot, textvariable=self.status, bg=BG, fg="#444").grid(row=0, column=3, padx=10)
        if not self.audio_ok:
            self.run_btn.configure(state="disabled")
            self.status.set("Audio indispo — Save WAV seul.")
        else:
            self.status.set("Pret. Clique un pas, puis une touche.")

    # ---------------- banques ----------------
    def _switch_bank(self, b):
        self.banks[self.cur_bank] = [dict(s) for s in self.steps]
        self.cur_bank = b
        if self.banks[b] is None:
            self.banks[b] = [{"note": None, "accent": False, "slide": False} for _ in range(16)]
        self.steps = [dict(s) for s in self.banks[b]]
        self.sel = 0
        self._refresh_strip()
        self._highlight_bank()
        self._changed()
        self.status.set(f"Pattern {b + 1}")

    def _highlight_bank(self):
        for i, b in enumerate(self.bank_btns):
            b.configure(bg=BANK_ON if i == self.cur_bank else "#d9d9d9",
                        fg="white" if i == self.cur_bank else "black")

    # ---------------- edition ----------------
    def _select(self, idx):
        self.sel = idx
        self._refresh_strip()

    def _set_note(self, note):
        self.steps[self.sel]["note"] = note
        self._refresh_strip()
        self._changed()
        self.sel = (self.sel + 1) % 16
        self._refresh_strip()

    def _toggle(self, key):
        self.steps[self.sel][key] = not self.steps[self.sel][key]
        self._refresh_strip()
        self._changed()

    def _octave(self, d):
        n = self.steps[self.sel]["note"]
        if not n:
            return
        self.steps[self.sel]["note"] = f"{n[:-1]}{int(n[-1]) + d}"
        self._refresh_strip()
        self._changed()

    def _refresh_strip(self):
        for i, c in enumerate(self.cells):
            st = self.steps[i]
            txt = st["note"] or "\u00b7"
            if st["accent"]:
                txt += " A"
            if st["slide"]:
                txt += " S"
            bg = SEL if i == self.sel else ("#e9e9e9" if st["note"] else "#d2d2d2")
            fg = RED if st["accent"] else (BLUE if st["slide"] else "black")
            c.configure(text=f"{i+1}\n{txt}", bg=bg, fg=fg)

    # ---------------- audio ----------------
    def _collect(self):
        return [dict(s) for s in self.steps]

    def _params(self):
        return dict(bpm=self.knobs["bpm"].get(), waveform=self.waveform.get(),
                    cutoff=self.knobs["cutoff"].get(), resonance=self.knobs["resonance"].get(),
                    env_mod=self.knobs["env_mod"].get(), decay=self.knobs["decay"].get(),
                    accent=self.knobs["accent"].get(), distortion=self.knobs["distortion"].get(),
                    tuning=self.knobs["tuning"].get(), swing=self.knobs["shuffle"].get(),
                    subdiv=SCALE_MAP[self.scale.get()], play_mode=PLAYMODES[self.playmode.get()])

    def _render(self, repeats=1):
        audio = self.tb.render(self._collect(), repeats=repeats, **self._params())
        vol = self.knobs["volume"].get()
        return np.clip(audio * vol / 0.9, -1.0, 1.0)

    def _changed(self, *_):
        if self.playing and self.audio_ok:
            self._play_loop()

    def _play_loop(self):
        audio = self._render(1)
        m = np.max(np.abs(audio)) or 1.0
        data = np.ascontiguousarray((audio / m * 0.95 * 32767).astype(np.int16))
        pygame.mixer.stop()
        self._snd = pygame.sndarray.make_sound(data)
        self._snd.play(loops=-1)
        self.status.set(f"\u25b6 {self.playmode.get()} | {self.scale.get()} | "
                        f"{self.knobs['bpm'].get():.0f} BPM")

    def toggle_run(self):
        if not self.audio_ok:
            return
        if self.playing:
            self.stop()
        else:
            self.playing = True
            self.run_btn.configure(text="\u23f8\nPAUSE")
            self._play_loop()

    def stop(self):
        self.playing = False
        self.run_btn.configure(text="\u25b6\nRUN")
        if self.audio_ok:
            pygame.mixer.stop()
        self.status.set("Stop.")

    def save(self):
        path = filedialog.asksaveasfilename(defaultextension=".wav",
                                            filetypes=[("WAV", "*.wav")],
                                            initialfile="tb303_pattern.wav")
        if not path:
            return
        try:
            self.status.set("Rendu…")
            self.root.update_idletasks()
            self.tb.write_wav(self._render(4), path)
            self.status.set(f"Enregistre : {path}")
        except Exception as e:
            messagebox.showerror("Erreur", str(e))

    def clear(self):
        for s in self.steps:
            s.update(note=None, accent=False, slide=False)
        self.sel = 0
        self._refresh_strip()
        self._changed()

    def load_demo(self):
        self._load_pattern(DEMO_PATTERN)
        self.sel = 0
        self._refresh_strip()
        self._changed()


def main():
    root = tk.Tk()
    TB303Studio(root)
    root.mainloop()


if __name__ == "__main__":
    main()
