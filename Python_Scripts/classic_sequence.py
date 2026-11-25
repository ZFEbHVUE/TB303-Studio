"""Musical data for the Studio. Pitch events and clock steps are independent.

No Tk, audio driver, or project paths are needed to use/test this module.
Indexes in memory and files are zero based. The UI uses group/section/1..8.
"""
from copy import deepcopy
import json, zlib
from collections import deque
from dataclasses import dataclass, field
from tb303 import name_to_midi, midi_to_name, parse_step

SLOTS, STEPS, TRACKS, BARS = 64, 16, 7, 64


def label(slot):
    return f"{slot // 16 + 1}{'AB'[(slot // 8) % 2]}-{slot % 8 + 1}"


def between(v, lo, hi, field):
    if type(v) is not int or not lo <= v <= hi:
        raise ValueError(f"{field}: expected a whole number from {lo} to {hi}.")
    return v


def pitch(note=None, accent=False, slide=False):
    if note is not None:
        if not isinstance(note, str) or not 0 <= name_to_midi(note) <= 127:
            raise ValueError(f"Invalid MIDI note: {note!r}")
    return dict(note=note, accent=bool(accent), slide=bool(slide))


def transposed(note, semitones):
    return None if note is None else midi_to_name(max(0, min(127, name_to_midi(note) + semitones)))


@dataclass
class Pattern:
    length: int = 16
    pitches: list = field(default_factory=list)
    time: list = field(default_factory=lambda: ["R"] * STEPS)
    # Unpitched editor cells can have flags before a note is entered.
    flags: dict = field(default_factory=dict)

    @classmethod
    def from_grid(cls, grid):
        obj = cls()
        obj.replace_grid(grid or [])
        return obj

    def replace_grid(self, grid):
        unused = self.pitches[self.time.count("N"):]
        seq = [parse_step(s) for s in grid][:STEPS]
        self.pitches, self.time, self.flags = [], [], {}
        for i, s in enumerate(seq):
            kind = "T" if s.get("tie") else "N" if s["note"] or s.get("on") else "R"
            self.time.append(kind)
            p = pitch(s["note"], s["accent"], s["slide"])
            if kind == "N":
                self.pitches.append(p)
            elif p["accent"] or p["slide"]:
                self.flags[i] = p
        self.time.extend(["R"] * (STEPS - len(seq)))
        self.pitches = (self.pitches + unused)[:STEPS]

    def grid(self, active=False):
        out, j = [], 0
        for i, kind in enumerate(self.time[:self.length if active else STEPS]):
            if kind == "N":
                p = dict(self.pitches[j]) if j < len(self.pitches) else pitch()
                if not p["note"]:
                    p["on"] = True
                j += 1
            else:
                p = dict(self.flags.get(i, pitch()))
                if kind == "T":
                    p["tie"] = True
            out.append(p)
        return out

    def write_pitch(self, pos, note, accent=None, slide=None):
        between(pos, 0, STEPS - 1, "pitch")
        while len(self.pitches) <= pos:
            self.pitches.append(pitch())
        old = self.pitches[pos]
        self.pitches[pos] = pitch(note, old["accent"] if accent is None else accent,
                                 old["slide"] if slide is None else slide)

    def write_time(self, pos, kind):
        between(pos, 0, self.length - 1, "step")
        if kind not in ("N", "T", "R"):
            raise ValueError("Timing must be a note, tie or rest.")
        self.time[pos] = kind
        self.flags.pop(pos, None)

    def shift_cell(self, pos, insert):
        """Keep active length fixed, shift only that region; inactive tail survives."""
        between(pos, 0, self.length - 1, "step")
        cells = self.grid()
        active = cells[:self.length]
        if insert:
            active.insert(pos, pitch())
            active.pop()
        else:
            active.pop(pos)
            active.append(pitch())
        self.replace_grid(active + cells[self.length:])

    def dump(self):
        return dict(length=self.length, pitches=deepcopy(self.pitches), time=list(self.time),
                    flags={str(i): dict(p) for i, p in self.flags.items()})

    @classmethod
    def read(cls, data):
        if not isinstance(data, dict):
            raise ValueError("Invalid Classic pattern.")
        l = between(data.get("length", 16), 1, 16, "length")
        times, pitches = data.get("time"), data.get("pitches")
        if not isinstance(times, list) or len(times) != 16 or any(x not in ("N","T","R") for x in times):
            raise ValueError("Expected 16 valid timing steps.")
        if not isinstance(pitches, list) or len(pitches) > 16:
            raise ValueError("Invalid pitch list.")
        flags = {between(int(i),0,15,"step"): pitch(**p) for i,p in data.get("flags",{}).items()}
        return cls(l, [pitch(**p) for p in pitches], list(times), flags)


@dataclass
class Track:
    bars: list = field(default_factory=list)   # (slot, transposition)
    segno: int | None = None
    dc: int | None = None                     # None: loop after last bar

    def put(self, pos, slot, shift=0, insert=False):
        between(slot, 0, SLOTS-1, "pattern")
        between(shift, -24, 24, "transposition")
        between(pos, 0, len(self.bars), "bar")
        if insert or pos == len(self.bars):
            if len(self.bars) >= BARS:
                raise ValueError("Track is full (64 bars).")
            self.bars.insert(pos, (slot, shift))
            for k in ("segno", "dc"):
                i = getattr(self, k)
                if i is not None and i >= pos:
                    setattr(self, k, i + 1)
        else:
            self.bars[pos] = (slot, shift)

    def remove(self, pos):
        between(pos, 0, len(self.bars)-1, "bar")
        self.bars.pop(pos)
        for k in ("segno", "dc"):
            i = getattr(self, k)
            if i is not None and i >= pos:
                setattr(self, k, None if i == pos else i-1)

    @property
    def end(self):
        return self.dc if self.dc is not None else len(self.bars)-1

    def mark(self, name, pos):
        if name not in ("segno","dc"):
            raise ValueError("Unknown track marker.")
        if pos is not None:
            between(pos,0,len(self.bars)-1,"marker")
        sg = pos if name == "segno" else self.segno
        dc = pos if name == "dc" else self.dc
        if sg is not None and dc is not None and sg >= dc:
            raise ValueError("SEGNO must come before D.C.")
        setattr(self,name,pos)

    def after(self, pos, request=None):
        if request == "reset":
            return 0
        if request == "ds" and self.segno is not None:
            return self.segno
        return 0 if pos >= self.end else pos+1

    def dump(self):
        return dict(bars=[list(b) for b in self.bars], segno=self.segno, dc=self.dc)

    @classmethod
    def read(cls, data):
        if not isinstance(data, dict) or not isinstance(data.get("bars"),list):
            raise ValueError("Invalid Classic track.")
        obj = cls()
        for slot, shift in data["bars"]:
            obj.put(len(obj.bars),slot,shift)
        for k in ("dc","segno"):
            obj.mark(k,data.get(k))
        return obj


class History:
    """Snapshots only for edits; navigation/transport never allocate an entry."""
    def __init__(self, limit=96):
        self.past, self.future = deque(maxlen=limit), deque(maxlen=limit)

    def commit(self, old, new, title):
        if old["data"] != new["data"]:
            def packed(x):
                raw=json.dumps(x["data"],separators=(",",":"),allow_nan=False).encode()
                return (zlib.compress(raw,1),x["where"])
            self.past.append((title,packed(old),packed(new)))
            self.future.clear()

    def move(self, redo=False):
        src, dst = (self.future,self.past) if redo else (self.past,self.future)
        if not src:
            return None
        item = src.pop()
        dst.append(item)
        blob,where=item[2 if redo else 1]
        return item[0], {"data":json.loads(zlib.decompress(blob)),"where":where}

