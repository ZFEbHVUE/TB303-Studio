#!/usr/bin/env python3
"""
midi_sniff.py -- Find out exactly what a MIDI controller sends.

Run this once, play with every control, press Ctrl-C. It prints a report that
says: which notes the keys send, which CC each knob sends and whether those
knobs are absolute or relative encoders, what the pads send, and whether the
joystick / wheels / transport emit anything usable.

That report is what the mapping file should be written from -- guessing at a
controller's CC layout from its manual is how mappings end up wrong.

    python midi_sniff.py              # auto-pick the first non-through port
    python midi_sniff.py --list       # just list ports
    python midi_sniff.py --port "MPK" # substring match on the port name
    python midi_sniff.py --raw        # also dump every message as it arrives

Needs: pip install mido python-rtmidi
On Debian/Ubuntu, python-rtmidi needs ALSA headers to build:
    sudo apt install libasound2-dev
"""

import argparse
import collections
import sys
import time

try:
    import mido
except ImportError:
    sys.exit("mido is missing:  pip install mido python-rtmidi")


# ---------------------------------------------------------------------------
# Port selection
# ---------------------------------------------------------------------------

# ALSA always exposes a loopback port; it is never the device we want.
SKIP = ("midi through", "midi-through", "rtmidi")


def list_ports():
    names = mido.get_input_names()
    if not names:
        print("No MIDI input ports found.")
        print("Is the controller plugged in and powered? Check with:  aconnect -l")
        return names
    print("MIDI input ports:")
    for i, n in enumerate(names):
        tag = "  (skipped: loopback)" if any(s in n.lower() for s in SKIP) else ""
        print(f"  [{i}] {n}{tag}")
    return names


def pick_port(want=None):
    names = mido.get_input_names()
    if not names:
        return None
    if want:
        for n in names:
            if want.lower() in n.lower():
                return n
        print(f"No port matching {want!r}. Available:")
        for n in names:
            print("   ", n)
        return None
    for n in names:
        if not any(s in n.lower() for s in SKIP):
            return n
    return names[0]


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


class Collector:
    """Accumulates everything seen, then reports on it."""

    def __init__(self):
        self.notes = collections.defaultdict(list)   # channel -> [note, ...]
        self.vels = []
        self.cc = collections.defaultdict(list)      # (chan, cc) -> [value, ...]
        self.pitchwheel = []
        self.aftertouch = []
        self.polytouch = []
        self.program = []
        self.clock = 0
        self.transport = []
        self.sysex = []
        self.other = collections.Counter()
        self.total = 0
        self.t0 = None

    def feed(self, m):
        self.total += 1
        if self.t0 is None:
            self.t0 = time.time()

        t = m.type
        if t == "note_on" and m.velocity > 0:
            self.notes[m.channel].append(m.note)
            self.vels.append(m.velocity)
        elif t in ("note_off",) or (t == "note_on" and m.velocity == 0):
            pass                                  # note-offs carry no new info
        elif t == "control_change":
            self.cc[(m.channel, m.control)].append(m.value)
        elif t == "pitchwheel":
            self.pitchwheel.append(m.pitch)
        elif t == "aftertouch":
            self.aftertouch.append(m.value)
        elif t == "polytouch":
            self.polytouch.append(m.value)
        elif t == "program_change":
            self.program.append(m.program)
        elif t == "clock":
            self.clock += 1
        elif t in ("start", "stop", "continue", "songpos"):
            self.transport.append(t)
        elif t == "sysex":
            self.sysex.append(len(m.data))
        else:
            self.other[t] += 1


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def classify_cc(values):
    """Absolute pot, relative encoder, or switch? Returns (kind, detail)."""
    uniq = sorted(set(values))
    n = len(values)

    # Relative encoders are tested FIRST, because the 1/127 convention emits
    # only two distinct values and would otherwise look like a switch. What
    # separates them: a switch alternates 0/127 a handful of times, an encoder
    # fires a burst of 1s or 127s while you spin it.
    near_64 = sum(1 for v in values if 60 <= v <= 68)
    extremes = sum(1 for v in values if v <= 3 or v >= 124)

    if n >= 6 and near_64 / n > 0.85 and max(uniq) - min(uniq) <= 12:
        return "relative", "signed-bit / 2's-comp around 64 (64+n up, 64-n down)"
    if n >= 6 and extremes / n > 0.85 and set(uniq) <= {1, 2, 126, 127}:
        return "relative", "inc/dec at the extremes (1 up, 127 down)"

    # A switch: only ever two values, typically 0 and 127, and few of them.
    if len(uniq) <= 2 and n >= 2:
        return "switch", f"values {uniq}"

    # Absolute: a wide, well-spread sweep.
    span = max(uniq) - min(uniq)
    if span >= 40:
        return "absolute", f"swept {min(uniq)}..{max(uniq)}"
    return "unclear", f"{n} msgs, range {min(uniq)}..{max(uniq)} — move it further"


NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_name(n):
    return f"{NOTE_NAMES[n % 12]}{n // 12 - 1}"


def report(c):
    print("\n" + "=" * 64)
    print(f"REPORT — {c.total} messages", end="")
    if c.t0:
        print(f" over {time.time() - c.t0:.0f}s")
    else:
        print()
    print("=" * 64)

    if not c.total:
        print("\nNothing received. The port opened but the device sent nothing.")
        print("Check you moved controls, and that the device is on the port shown.")
        return

    # --- keys
    if c.notes:
        print("\n--- NOTES (keys and pads) ---")
        for ch in sorted(c.notes):
            ns = c.notes[ch]
            lo, hi = min(ns), max(ns)
            print(f"  channel {ch + 1:2d} (0-based {ch}): {len(ns)} notes, "
                  f"{lo}..{hi}  [{note_name(lo)}..{note_name(hi)}]")
            span = hi - lo + 1
            if span <= 16:
                print(f"      narrow span ({span}) -> probably the PADS")
            elif span >= 24:
                print(f"      wide span ({span}) -> probably the KEYBOARD")
        if c.vels:
            print(f"  velocity: {min(c.vels)}..{max(c.vels)} "
                  f"(median {sorted(c.vels)[len(c.vels) // 2]})")
            if min(c.vels) == max(c.vels):
                print("      SAME velocity every time -> Full Level is on, "
                      "or the keybed is not velocity-sensitive here")
    else:
        print("\n--- NOTES: none seen ---")

    # --- CCs
    if c.cc:
        print("\n--- CONTROL CHANGE (knobs, joystick, wheels, buttons) ---")
        for (ch, num) in sorted(c.cc):
            vals = c.cc[(ch, num)]
            kind, detail = classify_cc(vals)
            print(f"  CC{num:<4d} ch{ch + 1:<3d} {len(vals):>4d} msgs  "
                  f"{kind:<9s} {detail}")
        kinds = {classify_cc(v)[0] for v in c.cc.values()}
        print()
        if "relative" in kinds:
            print("  !! Relative encoders present: the handler must ACCUMULATE")
            print("     deltas, not assign the value. See the mapping notes.")
        if "absolute" in kinds:
            print("  Absolute pots present: soft takeover is needed when "
                  "switching banks or presets.")
    else:
        print("\n--- CONTROL CHANGE: none seen ---")

    # --- expression
    if c.pitchwheel:
        print(f"\n--- PITCH WHEEL: {len(c.pitchwheel)} msgs, "
              f"{min(c.pitchwheel)}..{max(c.pitchwheel)} (range -8192..8191)")
    if c.aftertouch:
        print(f"--- CHANNEL AFTERTOUCH: {len(c.aftertouch)} msgs, "
              f"{min(c.aftertouch)}..{max(c.aftertouch)}")
    if c.polytouch:
        print(f"--- POLY AFTERTOUCH: {len(c.polytouch)} msgs")
    if c.program:
        print(f"--- PROGRAM CHANGE: {sorted(set(c.program))}")

    # --- timing
    if c.clock:
        print(f"\n--- MIDI CLOCK: {c.clock} ticks "
              f"({c.clock / 24:.1f} beats at 24 ppqn)")
        print("    The device is sending clock. For the synth engine, prefer")
        print("    making Python the clock master and ignoring this.")
    if c.transport:
        print(f"--- TRANSPORT: {collections.Counter(c.transport)}")
    if c.sysex:
        print(f"--- SYSEX: {len(c.sysex)} messages, sizes {sorted(set(c.sysex))}")
    if c.other:
        print(f"--- OTHER: {dict(c.other)}")

    # --- what to do next
    print("\n--- SUGGESTED MAPPING SKELETON ---")
    abs_ccs = [k for k, v in sorted(c.cc.items()) if classify_cc(v)[0] == "absolute"]
    rel_ccs = [k for k, v in sorted(c.cc.items()) if classify_cc(v)[0] == "relative"]
    if abs_ccs or rel_ccs:
        print("KNOBS = {")
        for (ch, num) in (abs_ccs + rel_ccs):
            mode = "abs" if (ch, num) in abs_ccs else "rel"
            print(f"    {num}: ('PARAM_NAME', '{mode}'),   # channel {ch}")
        print("}")
    kb = [ch for ch in c.notes if max(c.notes[ch]) - min(c.notes[ch]) >= 24]
    pd = [ch for ch in c.notes if max(c.notes[ch]) - min(c.notes[ch]) < 16]
    if kb:
        print(f"KEYBOARD_CHANNEL = {kb[0]}")
    if pd:
        print(f"PAD_CHANNEL = {pd[0]}")
        print(f"PAD_NOTES = {sorted(set(c.notes[pd[0]]))}")
    print()


# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser(description="Identify what a MIDI controller sends")
    ap.add_argument("--list", action="store_true", help="list ports and exit")
    ap.add_argument("--port", help="substring of the port name to open")
    ap.add_argument("--raw", action="store_true", help="print every message")
    ap.add_argument("--clock", action="store_true",
                    help="print clock ticks too (very noisy)")
    args = ap.parse_args()

    if args.list:
        list_ports()
        return

    name = pick_port(args.port)
    if name is None:
        list_ports()
        sys.exit("\nNo usable MIDI input. Plug the controller in and retry.")

    print(f"Listening on: {name}")
    print("\nDo all of this, then press Ctrl-C:")
    print("  1. play the lowest and the highest key")
    print("  2. play one key softly, then as hard as you can")
    print("  3. turn EACH of the 8 knobs fully left, then fully right")
    print("  4. hit each pad, and switch pad banks")
    print("  5. move the joystick, the pitch and mod wheels")
    print("  6. press the transport buttons, and run the sequencer briefly")
    print()

    c = Collector()
    try:
        with mido.open_input(name) as port:
            for m in port:
                if m.type == "clock" and not args.clock:
                    c.feed(m)
                    continue
                c.feed(m)
                if args.raw:
                    print("   ", m)
                elif c.total % 50 == 0:
                    print(f"\r  {c.total} messages...", end="", flush=True)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"\nPort error: {exc}")
    report(c)


if __name__ == "__main__":
    main()
