#!/usr/bin/env python3
"""
tb303.py - TB-303 Bass Line-style emulation (numpy only).

Chain: anti-aliased saw/square oscillator (PolyBLEP) -> resonant low-pass
ladder filter (~18 dB/oct) with saturation -> VCF + VCA envelopes, ACCENT,
SLIDE. Step sequencer with subdivision (Scale), swing (Shuffle) and playback
modes (Play Mode).

Step notation: "C2" | "C2+" (accent) | "C2~" (slide) | "C2+~" | "." (rest)
Or dict: {"note":"C2", "accent":True, "slide":False}

Example: python tb303.py   ->  tb303_demo.wav
"""

import re
import wave
import math
import random
import numpy as np

NOTE_OFFSETS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
NAMES_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_to_freq(name, tuning=440.0):
    return tuning * 2.0 ** ((name_to_midi(name) - 69) / 12.0)


def name_to_midi(name):
    m = re.match(r"^([A-Ga-g])([#b]?)(-?\d+)$", name.strip())
    if not m:
        raise ValueError(f"note invalide : {name!r}")
    letter, acc, octv = m.group(1).upper(), m.group(2), int(m.group(3))
    semi = NOTE_OFFSETS[letter] + (1 if acc == "#" else -1 if acc == "b" else 0)
    return (octv + 1) * 12 + semi


def midi_to_name(midi):
    midi = int(round(midi))
    return f"{NAMES_SHARP[midi % 12]}{midi // 12 - 1}"


def parse_step(s):
    if isinstance(s, dict):
        return {"note": s.get("note"), "accent": bool(s.get("accent")),
                "slide": bool(s.get("slide"))}
    s = str(s).strip()
    if s in (".", "", "-", "r", "R"):
        return {"note": None, "accent": False, "slide": False}
    return {"note": s.replace("+", "").replace("~", ""),
            "accent": "+" in s, "slide": "~" in s}


def apply_play_mode(steps, mode):
    """Reorder/transform the steps according to the playback mode."""
    if mode == "reverse":
        return list(reversed(steps))
    if mode == "fwd_rev":
        return list(steps) + list(reversed(steps))
    if mode == "random":
        s = list(steps)
        random.shuffle(s)
        return s
    if mode == "invert":
        midis = [name_to_midi(s["note"]) for s in steps if s["note"]]
        if not midis:
            return list(steps)
        center = round(sum(midis) / len(midis))
        out = []
        for s in steps:
            if s["note"]:
                nm = midi_to_name(max(12, min(96, 2 * center - name_to_midi(s["note"]))))
                out.append({**s, "note": nm})
            else:
                out.append(dict(s))
        return out
    return list(steps)


class TB303:
    def __init__(self, sample_rate=44100):
        self.sr = sample_rate

    @staticmethod
    def _polyblep(t, dt):
        out = np.zeros_like(t)
        m = t < dt
        x = t[m] / dt[m]
        out[m] = x + x - x * x - 1.0
        m = t > 1.0 - dt
        x = (t[m] - 1.0) / dt[m]
        out[m] = x * x + x + x + 1.0
        return out

    def _osc(self, pitch_hz, waveform):
        dt = np.clip(pitch_hz / self.sr, 1e-6, 0.5)
        phase = np.cumsum(dt) % 1.0
        if waveform == "square":
            naive = np.where(phase < 0.5, 1.0, -1.0)
            return naive + self._polyblep(phase, dt) \
                         - self._polyblep((phase + 0.5) % 1.0, dt)
        naive = 2.0 * phase - 1.0
        return naive - self._polyblep(phase, dt)

    def render(self, pattern, bpm=130, waveform="saw", cutoff=0.35,
               resonance=0.78, env_mod=0.55, decay=0.45, accent=0.6,
               distortion=0.0, tuning=440.0, gate_len=0.55, repeats=1,
               subdiv=4, swing=0.0, play_mode="forward"):
        steps = apply_play_mode([parse_step(s) for s in pattern], play_mode)
        steps = steps * repeats
        sr = self.sr
        nst = len(steps)
        if nst == 0:
            return np.zeros((0, 2))

        step_dur = 60.0 / bpm / max(subdiv, 1)
        swing = max(0.0, min(0.66, swing))
        lengths = [max(1, int(round(step_dur * ((1.0 + swing) if i % 2 == 0
                                                else (1.0 - swing)) * sr)))
                   for i in range(nst)]
        starts = np.concatenate([[0], np.cumsum(lengths)]).astype(int)
        N = int(starts[-1])
        slide_samps = int(0.060 * sr)

        # --- control signals ---
        target_pitch = np.zeros(N)
        gate = np.zeros(N)
        accent_amp = np.zeros(N)
        attacks, acc_at_attack = [], []
        prev_slide = False
        last_freq = 0.0
        for i, st in enumerate(steps):
            if st["note"]:
                last_freq = note_to_freq(st["note"], tuning)
                break
        if last_freq == 0.0:
            last_freq = 110.0

        for i, st in enumerate(steps):
            a, b = int(starts[i]), int(starts[i + 1])
            rest = st["note"] is None
            f = 0.0 if rest else note_to_freq(st["note"], tuning)
            target_pitch[a:b] = f if f > 0 else last_freq
            if f > 0:
                last_freq = f
            if rest:
                prev_slide = False
                continue
            g_end = b if st["slide"] else a + int(gate_len * (b - a))
            gate[a:min(g_end, N)] = 1.0
            if st["accent"]:
                accent_amp[a:min(g_end, N)] = accent
            if not prev_slide:
                attacks.append(a)
                acc_at_attack.append(accent if st["accent"] else 0.0)
            prev_slide = st["slide"]

        # --- glissando (slide) ---
        pitch = target_pitch.copy()
        glide_mask = np.zeros(N, dtype=bool)
        for i, st in enumerate(steps[:-1]):
            if st["slide"] and st["note"] and steps[i + 1]["note"]:
                bnd = int(starts[i + 1])
                glide_mask[bnd:min(bnd + slide_samps, N)] = True
        gc = 1.0 - math.exp(-1.0 / max(slide_samps, 1))
        p = pitch[0] if N else 0.0
        for i in range(N):
            p = p + gc * (target_pitch[i] - p) if glide_mask[i] else target_pitch[i]
            pitch[i] = p

        # --- VCF envelope ---
        filt_env = np.zeros(N)
        acc_env = np.zeros(N)
        tau = 0.04 + decay * 1.6
        na = max(int(0.003 * sr), 1)
        bounds = attacks + [N]
        for k, a in enumerate(attacks):
            end = bounds[k + 1]
            seg = end - a
            if seg <= 0:
                continue
            t = np.arange(seg) / sr
            e = np.where(np.arange(seg) < na, np.arange(seg) / na,
                         np.exp(-(t - na / sr) / tau))
            filt_env[a:end] = e
            acc_env[a:end] = e * acc_at_attack[k]

        osc = self._osc(pitch, waveform)
        base_fc = 30.0 * (10000.0 / 30.0) ** cutoff
        fc = base_fc * np.power(2.0, env_mod * 6.0 * filt_env + 2.0 * acc_env)
        fc = np.clip(fc, 20.0, 0.45 * sr)
        g = 1.0 - np.exp(-2.0 * np.pi * fc / sr)

        # --- 303-style filter: 4-stage ladder, output tapped at the 3rd pole
        #     (~18 dB/oct, brighter than a Moog's 24 dB), feedback from the 4th pole ---
        res_amt = resonance * 4.2            # resonant peak -> near self-oscillation
        s1 = s2 = s3 = s4 = ae = 0.0
        a_atk = 1.0 - math.exp(-1.0 / (sr * 0.003))
        a_rel = 1.0 - math.exp(-1.0 / (sr * 0.008))
        out = np.empty(N)
        for i in range(N):
            gi = g[i]
            inp = math.tanh(osc[i] - res_amt * s4)   # saturate input + feedback (4th pole)
            s1 += gi * (inp - s1)
            s2 += gi * (s1 - s2)
            s3 += gi * (s2 - s3)
            s4 += gi * (s3 - s4)
            target = gate[i] * (1.0 + accent_amp[i] * 0.8)
            ae += (a_atk if target > ae else a_rel) * (target - ae)
            out[i] = s3 * 1.9 * ae           # 3rd-pole output = 18 dB/oct (303 grain)

        if distortion > 0:
            drive = 1.0 + distortion * 20.0
            out = np.tanh(drive * out) / math.tanh(drive)

        peak = np.max(np.abs(out)) or 1.0
        out = out / peak * 0.9
        return np.stack([out, out], axis=1)

    def write_wav(self, audio, path, peak=0.95, normalize=False):
        if normalize:
            m = np.max(np.abs(audio)) or 1.0
            audio = audio / m * peak
        data = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
        ch = 2 if audio.ndim == 2 else 1
        with wave.open(path, "w") as w:
            w.setnchannels(ch)
            w.setsampwidth(2)
            w.setframerate(self.sr)
            w.writeframes(data.tobytes())
        return path


DEMO_PATTERN = [
    "C2", "C2~", "C3", "C2+", "D#2", "C2~", "C3", "A#1",
    "C2", "G2~", "C3+", "C2", "D#2", "C2", "A#1~", "C2+",
]


def main():
    tb = TB303()
    a = tb.render(DEMO_PATTERN, bpm=130, cutoff=0.32, resonance=0.8,
                  env_mod=0.6, decay=0.5, accent=0.6, distortion=0.2,
                  repeats=4, swing=0.15)
    tb.write_wav(a, "tb303_demo.wav")
    print(f"OK -> tb303_demo.wav ({len(a)/tb.sr:.1f}s)")


if __name__ == "__main__":
    main()
