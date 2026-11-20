#!/usr/bin/env python3
"""
midi_in.py -- MIDI control surface for TB-303 Studio (Akai MPK mini Plus).

Drop this next to tb303_studio.py; the studio imports it on its own.

THE WHOLE SURFACE
-----------------
  K1 tuning    K2 cutoff   K3 resonance   K4 env mod
  K5 decay     K6 accent   K7 distortion  K8 volume
  Mod wheel    tempo (whole BPM)

  Pitch wheel  up -> saw,   down -> square      (it springs back to centre)
  Joystick     sideways push -> next shuffle value (0, .15, .30, .45, .60, 0...)
               vertical push -> REST on the selected step

  << PREV    CC115          previous step   } walk the pattern,
  >> NEXT    CC116          next step       } nothing is modified
  STOP       CC117          stop
  PLAY       CC118          run / stop
  REC        CC119          PLAY <-> WRITE          (recording == writing)

  Pads       1..8           patterns 1..8, in bank A and bank B alike

  Keys, PLAY mode   audition only: roam freely, nothing is written
  Keys, WRITE mode  write the note into the selected step, then advance
                    hit hard    -> accent on that step
                    play legato -> slide on that step

  OCT- / OCT+ shift the MPK's own keyboard: nothing to map, the next notes
  simply land an octave lower or higher.

Left on screen: scale, play mode, preset, clear, demo, and the menus.

MEASURED, NOT ASSUMED
---------------------
Every assignment here comes from a sniff of the actual unit (program PGM1):
  - knobs CC70..77 and the mod wheel CC1 sweep 0..127 absolute;
  - the joystick axes CC12 and CC2 REST AT 0, go to 127 when pushed, return
    to 0 and bounce up to ~55 on release;
  - the pitch wheel sends pitch bend, 0 at rest, +8191 at the top;
  - HOME, SHIFT, TAP TEMPO, PROG SELECT, BANK A/B, SCALES, CHORDS, ARP,
    NOTE REPEAT and SEQ send nothing at all.

THREADING
---------
python-rtmidi calls back on its own thread, and tkinter is not thread-safe.
The callback does one thing: append to a deque. The tk main loop drains it
via root.after(). No locks, no allocation in the callback.

STANDALONE TEST (no GUI, prints what each control would do):
    python midi_in.py
"""

import collections
import sys
import time

try:
    import mido
except ImportError:                                  # pragma: no cover
    raise SystemExit("mido is missing:  pip install mido python-rtmidi")


# ===========================================================================
# MAPPING -- everything you might want to change lives in this block
# ===========================================================================

KNOB_CC = {                  # the 8 knobs, in K1..K8 order, then the mod wheel
    70: "tuning",            # K1
    71: "cutoff",            # K2
    72: "resonance",         # K3
    73: "env_mod",           # K4
    74: "decay",             # K5
    75: "accent",            # K6
    76: "distortion",        # K7
    77: "volume",            # K8
    1:  "bpm",               # mod wheel: it holds position, so it acts as a knob
}

# A pot has no centre detent, so landing exactly on A=440 by hand is fiddly.
# Within this many Hz of 440 the tuning knob snaps to it.
TUNING_SNAP = 2.0

# --- the joystick: two one-shot pushes -------------------------------------
# Each axis rests at 0 and reads 0..127 however far it is pushed. A push fires
# once when it passes PUSH_FIRE, and the axis rearms only after coming back
# under PUSH_REARM -- so holding it does not repeat, and the bounce on release
# (measured up to ~55) cannot fire again.
JOY_CC = {
    12: "shuffle_next",      # sideways
    2:  "rest",              # up / down
}
PUSH_FIRE = 100
PUSH_REARM = 20

SHUFFLE_VALUES = (0.0, 0.15, 0.30, 0.45, 0.60)   # the studio allows 0 .. 0.66

# --- the pitch wheel: a two-way switch -------------------------------------
# Absolute, not a toggle: up is always saw, down is always square, so you never
# have to remember which one is active.
BEND_UP = "saw"
BEND_DOWN = "square"
BEND_FIRE = 6000             # of 8191
BEND_REARM = 1500

# --- transport buttons (all send 127 on press only) ------------------------
TRANSPORT_CC = {
    115: "prev_step",        # labelled PREV STEP on the panel
    116: "next_step",        # labelled NEXT STEP
    117: "stop",
    118: "run",
    119: "mode",             # REC: recording is writing
}

# --- pads: patterns, whichever bank the MPK is in --------------------------
PAD_CHANNEL = 9              # 0-based: MIDI channel 10
PAD_FIRST = 36               # bank A sends 36..43, bank B 44..51

# --- keyboard --------------------------------------------------------------
KEY_BASE = 48                # MIDI 48 == leftmost key of the on-screen piano (C1)
START_MODE = "write"         # "write" or "play"; REC switches, at any time
ACCENT_VELOCITY = 90         # your own sniff: velocities 26..127, median 56

# The 303 is monophonic, so a chord must write ONE step. With the MPK's Chords
# mode on, one key sends a triad at once; notes landing within this window
# count as one chord and only the first is kept. A chord arrives inside a
# millisecond, hand-played legato tens of milliseconds apart.
CHORD_WINDOW = 0.030         # seconds

LOG_ACTIONS = True           # print every action to the terminal
POLL_MS = 8                  # how often tk drains the queue (~125 Hz)
N_STEPS = 16
BADGE_XY = (1010, 728)       # where the PLAY/WRITE badge goes, in skin pixels

# ===========================================================================

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
SKIP_PORTS = ("midi through", "midi-through", "rtmidi")


def midi_to_note(n):
    """MIDI note number -> the studio's own note string ('C1', 'C#2', ...).

    The on-screen piano runs C1..B3 over 21 white keys, so MIDI 48..83 lands on
    it exactly. Below C0 the engine has nothing sensible to play, so clamp.
    """
    octave = (n - KEY_BASE) // 12 + 1
    return f"{NOTE_NAMES[n % 12]}{max(0, octave)}"


class Push:
    """A spring-loaded axis resting at a low value, used as a button."""

    def __init__(self, fire, rearm):
        self.fire, self.rearm = fire, rearm
        self.armed = True

    def update(self, value):
        """True exactly once per push."""
        if self.armed and value >= self.fire:
            self.armed = False
            return True
        if not self.armed and value <= self.rearm:
            self.armed = True
        return False


class Bend:
    """The pitch wheel as a two-way switch: returns +1, -1 or 0."""

    def __init__(self):
        self.armed = True

    def update(self, pitch):
        if self.armed and abs(pitch) >= BEND_FIRE:
            self.armed = False
            return 1 if pitch > 0 else -1
        if not self.armed and abs(pitch) <= BEND_REARM:
            self.armed = True
        return 0


def next_shuffle(current):
    """The next value of SHUFFLE_VALUES above `current`, wrapping to 0."""
    for v in SHUFFLE_VALUES:
        if v > current + 1e-6:
            return v
    return SHUFFLE_VALUES[0]


# ---------------------------------------------------------------------------


class MidiBridge:
    MODES = ("play", "write")

    def __init__(self, app, port_name=None, verbose=True):
        self.app = app
        self.verbose = verbose
        self.q = collections.deque(maxlen=4096)   # callback -> tk main loop
        self.port = None
        self.held = set()                         # keys down, for legato
        self._last_key_t = 0.0                    # for chord collapsing
        self.pushes = {cc: Push(PUSH_FIRE, PUSH_REARM) for cc in JOY_CC}
        self.bend = Bend()
        self.mode = START_MODE if START_MODE in self.MODES else "write"
        self._poll_job = None
        self._dropped = 0

        # Pull the studio's own tables out of its module, so this file never
        # imports tb303_studio (circular) and the studio can be renamed freely.
        mod = sys.modules[type(app).__module__]
        self.KNOB_SPEC = mod.KNOB_SPEC

        name = self._pick_port(port_name)
        if name is None:
            raise RuntimeError("no MIDI input port found")
        self.port_name = name
        self.port = mido.open_input(name, callback=self._on_midi)
        self._log(f"MIDI in: {name}")
        self._log(f"keys = {self.mode.upper()}   (REC switches)")
        self._draw_badge()
        self._schedule()

    # -- plumbing ---------------------------------------------------------

    @staticmethod
    def _pick_port(want):
        names = mido.get_input_names()
        if not names:
            return None
        if want:
            for n in names:
                if want.lower() in n.lower():
                    return n
            return None
        for n in names:
            if not any(s in n.lower() for s in SKIP_PORTS):
                return n
        return names[0]

    def _log(self, msg):
        if self.verbose:
            print(f"[midi] {msg}")

    def _on_midi(self, msg):
        """rtmidi thread. Does nothing but enqueue -- see the note at the top."""
        if msg.type in ("note_on", "note_off", "control_change", "pitchwheel"):
            if len(self.q) == self.q.maxlen:
                self._dropped += 1
            self.q.append(msg)

    def _schedule(self):
        self._poll_job = self.app.root.after(POLL_MS, self._poll)

    def _poll(self):
        """tk main thread: safe to touch the GUI and the audio engine here."""
        n = 0
        while self.q and n < 256:
            try:
                self._handle(self.q.popleft())
            except Exception as exc:                # never kill the GUI loop
                self._log(f"error: {exc}")
            n += 1
        if self._dropped:
            self._log(f"dropped {self._dropped} messages (queue full)")
            self._dropped = 0
        self._schedule()

    def close(self):
        if self._poll_job is not None:
            try:
                self.app.root.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None
        if self.port is not None:
            try:
                self.port.close()
            except Exception:
                pass
            self.port = None
        self._log("closed")

    # -- the PLAY / WRITE badge -------------------------------------------

    def _draw_badge(self):
        """Painted on the studio's canvas under our own tag.

        refresh() only clears the "dyn" tag, so this survives redraws and the
        studio itself needs no modification to show it.
        """
        try:
            cv, S = self.app.cv, self.app.S
            cv.delete("midi")
            play = self.mode == "play"
            cv.create_text(
                S(BADGE_XY[0]), S(BADGE_XY[1]), anchor="w",
                text=("MIDI ▸ PLAY" if play else "MIDI ● WRITE"),
                fill=("#8fd4a0" if play else "#ffcf6b"),
                font=("Georgia", max(8, int(S(11))), "bold"), tags="midi")
        except Exception:
            pass                                    # cosmetic, never fatal

    # -- dispatch ---------------------------------------------------------

    def _handle(self, m):
        t = m.type
        if t == "control_change":
            self._cc(m.control, m.value)
        elif t == "pitchwheel":
            d = self.bend.update(m.pitch)
            if d:
                self._action("wave_" + (BEND_UP if d > 0 else BEND_DOWN))
        elif t == "note_on" and m.velocity > 0:
            if m.channel == PAD_CHANNEL:
                self._pad(m.note)
            else:
                self._key_down(m)
        elif t == "note_off" or (t == "note_on" and m.velocity == 0):
            if m.channel != PAD_CHANNEL:
                self.held.discard(m.note)

    def _cc(self, cc, val):
        if cc in KNOB_CC:
            self._set_knob(KNOB_CC[cc], val / 127.0)
        elif cc in JOY_CC:
            if self.pushes[cc].update(val):
                self._action(JOY_CC[cc])
        elif cc in TRANSPORT_CC and val >= 64:
            self._action(TRANSPORT_CC[cc])

    # -- knobs ------------------------------------------------------------

    def _set_knob(self, name, frac):
        """frac is 0..1; map it onto the parameter's own range and push audio."""
        lo, hi, _, _ = self.KNOB_SPEC[name]
        value = lo + frac * (hi - lo)
        if name == "tuning" and abs(value - 440.0) <= TUNING_SNAP:
            value = 440.0                           # no detent on a pot: snap
        elif name == "bpm":
            value = float(round(value))             # whole BPM, as displayed
        if value == self.app.kv[name]:
            return                                  # nothing changed: no push
        self.app.kv[name] = value
        self.app._knob_live(name)                   # engine first, redraw coalesced
        if LOG_ACTIONS:
            self._log(f"{name} = {value:.2f}")

    # -- keyboard ---------------------------------------------------------

    def _key_down(self, m):
        note = midi_to_note(m.note)

        if self.mode == "play":
            self.app._preview(note)                 # audition, nothing written
            self.held.add(m.note)
            return

        # Collapse chords: one key press writes one step even when the MPK's
        # Chords mode turns it into a triad.
        now = time.monotonic()
        if now - self._last_key_t < CHORD_WINDOW:
            self.held.add(m.note)
            if LOG_ACTIONS:
                self._log(f"chord note {note} ignored (monophonic)")
            return
        self._last_key_t = now

        accent = m.velocity >= ACCENT_VELOCITY
        slide = bool(self.held)                     # a key still down: legato
        self.held.add(m.note)

        # Flags go on the step BEFORE _set_note, which writes the note, previews
        # it, then advances the cursor.
        step = self.app.steps[self.app.sel]
        step["accent"] = accent
        step["slide"] = slide
        self.app._set_note(note)
        if LOG_ACTIONS:
            tags = ("+" if accent else "") + ("~" if slide else "")
            self._log(f"write {note}{tags}  (vel {m.velocity})")

    # -- pads -------------------------------------------------------------

    def _pad(self, note):
        if not (PAD_FIRST <= note < PAD_FIRST + 16):
            return
        b = (note - PAD_FIRST) % 8                  # bank A and B alike
        self.app._switch_bank(b)
        self._draw_badge()
        if LOG_ACTIONS:
            self._log(f"pattern {b + 1}")

    # -- one place where every discrete action happens --------------------

    def _action(self, act):
        a = self.app
        if act == "mode":
            self.mode = "play" if self.mode == "write" else "write"
            self.held.clear()
            self._log(f"keys = {self.mode.upper()}")
        elif act == "prev_step":
            a.sel = (a.sel - 1) % N_STEPS
            a.refresh()
        elif act == "next_step":
            a.sel = (a.sel + 1) % N_STEPS
            a.refresh()
        elif act == "shuffle_next":
            a.kv["shuffle"] = next_shuffle(a.kv["shuffle"])
            a._knob_live("shuffle")
            self._log(f"shuffle = {a.kv['shuffle']:.2f}")
        elif act in ("wave_saw", "wave_square"):
            wave = act[5:]
            if a.waveform != wave:
                a.waveform = wave
                a._changed()
            self._log(f"waveform = {wave}")
        elif act in ("rest", "run", "stop"):
            a._button(act)
            self._log(act)
        self._draw_badge()


# ---------------------------------------------------------------------------


def attach(app, port_name=None, verbose=True):
    """Wire a MidiBridge onto a running SkinStudio. Returns it (keep a ref)."""
    return MidiBridge(app, port_name=port_name, verbose=verbose)


# ---------------------------------------------------------------------------
# Standalone test: no GUI, just print what each control would do.
# ---------------------------------------------------------------------------


def _selftest(port_name=None):
    name = MidiBridge._pick_port(port_name)
    if name is None:
        sys.exit("No MIDI input port. Plug the controller in.")
    print(f"Listening on {name} — Ctrl-C to stop.\n")
    print("Every control prints what it would do in the studio.")
    print(f"Keys start in {START_MODE.upper()} mode; REC switches.\n")

    mode = [START_MODE]
    pushes = {cc: Push(PUSH_FIRE, PUSH_REARM) for cc in JOY_CC}
    bend = Bend()
    shuffle = [0.0]
    try:
        with mido.open_input(name) as port:
            for m in port:
                if m.type == "control_change":
                    cc, v = m.control, m.value
                    if cc in KNOB_CC:
                        print(f"  knob CC{cc:<3d}  -> {KNOB_CC[cc]:<11s} {v / 127:.2f}")
                    elif cc in JOY_CC:
                        if pushes[cc].update(v):
                            a = JOY_CC[cc]
                            if a == "shuffle_next":
                                shuffle[0] = next_shuffle(shuffle[0])
                                a = f"shuffle -> {shuffle[0]:.2f}"
                            print(f"  joystick     -> {a}")
                    elif cc in TRANSPORT_CC and v >= 64:
                        a = TRANSPORT_CC[cc]
                        if a == "mode":
                            mode[0] = "play" if mode[0] == "write" else "write"
                            a = f"mode -> {mode[0].upper()}"
                        print(f"  transport    -> {a}")
                    else:
                        print(f"  CC{cc} = {v}   (unmapped)")
                elif m.type == "pitchwheel":
                    d = bend.update(m.pitch)
                    if d:
                        print(f"  pitch wheel  -> waveform {BEND_UP if d > 0 else BEND_DOWN}")
                elif m.type == "note_on" and m.velocity > 0:
                    if m.channel == PAD_CHANNEL:
                        print(f"  pad          -> pattern {(m.note - PAD_FIRST) % 8 + 1}")
                    else:
                        what = ("audition" if mode[0] == "play"
                                else "write step + advance")
                        acc = " ACCENT" if (mode[0] == "write"
                                            and m.velocity >= ACCENT_VELOCITY) else ""
                        print(f"  key {m.note:<3d}       -> {midi_to_note(m.note):<4s} "
                              f"vel {m.velocity:<4d} [{mode[0].upper()}: {what}]{acc}")
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    _selftest(sys.argv[1] if len(sys.argv) > 1 else None)
