"""
instruments_rt.py - real-time engine for non-303 voices (sampler + synth instruments).

Same idea as tb303_rt.py (continuous sounddevice callback, Numba-compiled DSP, params
read every block so knobs are instant), but instead of an oscillator it plays a *sample*
read at a pitch-dependent rate (linear interpolation, continuous position), then runs it
through the very same 303-style resonant ladder filter + envelopes + distortion. The
built-in synthetic voices (sax, brass) are pre-rendered once into a sample, so the engine
only ever has to do one thing: read a buffer and filter it.

Dependencies:  pip install numba sounddevice   (+ libportaudio2 on Linux)
"""
import os
import math
import threading
import numpy as np

if os.path.exists("/mnt/wslg/PulseServer"):
    os.environ.setdefault("PULSE_SERVER", "unix:/mnt/wslg/PulseServer")

try:
    from numba import njit
    _HAS_NUMBA = True
except Exception:
    _HAS_NUMBA = False
    def njit(*a, **k):
        def deco(f):
            return f
        return deco if not (a and callable(a[0])) else a[0]

try:
    import sounddevice as sd
    _HAS_SD = True
except Exception:
    _HAS_SD = False

from tb303 import DEMO_PATTERN
from tb303_rt import note_to_freq, parse_step

_HAS_RT_INSTR = _HAS_NUMBA and _HAS_SD       # real-time only worthwhile with both

# parameter indices (written by the GUI, read by the callback)
P_CUTOFF, P_RESO, P_ENVMOD, P_DECAY, P_ACCENT, P_BPM = 0, 1, 2, 3, 4, 5
P_DIST, P_VOL, P_SUBDIV, P_GATE, P_SWING, P_TUNING, P_PLAY = 6, 7, 8, 9, 10, 11, 12
NPARAMS = 13

# persistent state indices
S_POS, S_S1, S_S2, S_S3, S_S4, S_FENV, S_AENV = 0, 1, 2, 3, 4, 5, 6
S_FREQ, S_STEP, S_SIS, S_GATE, S_ACC, S_PREVSL, S_INIT, S_GLIDE = 7, 8, 9, 10, 11, 12, 13, 14
S_PREVF, S_PREVN, S_PREVPOS = 15, 16, 17
NSTATE = 18


@njit(cache=True, fastmath=True)
def synth_block(out, frames, st, pr, pat_f, pat_a, pat_s, nsteps, sr, sample, slen, base):
    cutoff = pr[P_CUTOFF]; reso = pr[P_RESO]; envmod = pr[P_ENVMOD]; decay = pr[P_DECAY]
    accent = pr[P_ACCENT]; bpm = pr[P_BPM]; dist = pr[P_DIST]; vol = pr[P_VOL]
    subdiv = pr[P_SUBDIV]; gate_len = pr[P_GATE]; swing = pr[P_SWING]
    tuning = pr[P_TUNING]; playing = pr[P_PLAY]

    res_amt = reso * 4.2
    base_fc = 30.0 * (10000.0 / 30.0) ** cutoff
    tau = 0.04 + decay * 1.6
    fdec = math.exp(-1.0 / (sr * tau))
    a_atk = 1.0 - math.exp(-1.0 / (sr * 0.003))
    a_rel = 1.0 - math.exp(-1.0 / (sr * 0.008))
    glide = 1.0 - math.exp(-1.0 / (sr * 0.035))
    step_dur = sr * 60.0 / max(bpm, 1.0) / max(subdiv, 1.0)
    tun = tuning / 440.0
    invbase = 1.0 / base if base > 0.0 else 1.0

    pos = st[S_POS]; s1 = st[S_S1]; s2 = st[S_S2]; s3 = st[S_S3]; s4 = st[S_S4]
    fenv = st[S_FENV]; aenv = st[S_AENV]; freq = st[S_FREQ]
    step = int(st[S_STEP]); sis = st[S_SIS]; gate = st[S_GATE]
    acc = st[S_ACC]; prevsl = st[S_PREVSL]; init = st[S_INIT]; glide_t = st[S_GLIDE]

    if slen < 2:
        for i in range(frames):
            out[i] = 0.0
        return

    # --- stopped: only the keyboard-audition one-shot may sound ---
    if playing < 0.5:
        prevn = st[S_PREVN]
        if prevn > 0.5:
            prevf = st[S_PREVF]; ppos = st[S_PREVPOS]; rel_at = 0.12 * sr
            inc = prevf * invbase
            for i in range(frames):
                if prevn <= 0.5:
                    out[i] = 0.0
                    continue
                g_on = 1.0 if prevn > rel_at else 0.0
                ip = int(ppos)
                if ip >= slen - 1:
                    smp = 0.0
                else:
                    fr = ppos - ip
                    smp = sample[ip] * (1.0 - fr) + sample[ip + 1] * fr
                ppos += inc
                aenv += (a_atk if g_on > aenv else a_rel) * (g_on - aenv)
                fenv *= fdec
                fc = base_fc * (2.0 ** (envmod * 6.0 * fenv))
                if fc > 16000.0:
                    fc = 16000.0
                if fc < 20.0:
                    fc = 20.0
                gi = 1.0 - math.exp(-2.0 * math.pi * fc / sr)
                inp = math.tanh(smp - res_amt * s4)
                s1 += gi * (inp - s1); s2 += gi * (s1 - s2)
                s3 += gi * (s2 - s3); s4 += gi * (s3 - s4)
                out[i] = math.tanh(s3 * 1.9 * aenv * vol)
                prevn -= 1.0
            st[S_PREVPOS] = ppos; st[S_PREVN] = prevn
            st[S_S1] = s1; st[S_S2] = s2; st[S_S3] = s3; st[S_S4] = s4
            st[S_FENV] = fenv; st[S_AENV] = aenv
        else:
            for i in range(frames):
                out[i] = 0.0
            st[S_AENV] = 0.0
        return

    # --- running sequencer ---
    for i in range(frames):
        sd = step_dur * (1.0 + swing) if (step % 2 == 0) else step_dur * (1.0 - swing)
        if init < 0.5 or sis >= sd:
            if init >= 0.5:
                step = (step + 1) % nsteps
                sis -= sd
            else:
                step = 0; sis = 0.0; init = 1.0
            f = pat_f[step]
            if f <= 0.0:
                gate = 0.0
            else:
                tgt = f * tun
                glide_t = tgt
                if prevsl > 0.5:               # legato slide: glide pitch, keep reading
                    pass
                else:
                    freq = tgt
                    fenv = 1.0
                    pos = 0.0                  # re-trigger the sample
                gate = 1.0
                acc = pat_a[step]
            prevsl = pat_s[step]

        freq += (glide_t - freq) * glide
        gate_samps = sd if prevsl > 0.5 else gate_len * sd
        g_on = 1.0 if (gate > 0.5 and sis < gate_samps) else 0.0

        ip = int(pos)
        if ip >= slen - 1:
            smp = 0.0
        else:
            frac = pos - ip
            smp = sample[ip] * (1.0 - frac) + sample[ip + 1] * frac
        pos += freq * invbase

        acc_boost = 1.0 + accent * acc
        target = g_on * acc_boost
        aenv += (a_atk if target > aenv else a_rel) * (target - aenv)
        fenv *= fdec

        fc = base_fc * (2.0 ** (envmod * 6.0 * fenv + accent * acc * 1.5))
        if fc > 16000.0:
            fc = 16000.0
        if fc < 20.0:
            fc = 20.0
        gi = 1.0 - math.exp(-2.0 * math.pi * fc / sr)
        inp = math.tanh(smp - res_amt * s4)
        s1 += gi * (inp - s1)
        s2 += gi * (s1 - s2)
        s3 += gi * (s2 - s3)
        s4 += gi * (s3 - s4)
        y = s3 * 1.9 * aenv
        if dist > 0.0:
            drive = 1.0 + dist * 18.0
            y = math.tanh(y * drive) / math.tanh(drive)
        out[i] = math.tanh(y * vol)
        sis += 1.0

    st[S_POS] = pos; st[S_S1] = s1; st[S_S2] = s2; st[S_S3] = s3; st[S_S4] = s4
    st[S_FENV] = fenv; st[S_AENV] = aenv; st[S_FREQ] = freq
    st[S_STEP] = step; st[S_SIS] = sis; st[S_GATE] = gate
    st[S_ACC] = acc; st[S_PREVSL] = prevsl; st[S_INIT] = init; st[S_GLIDE] = glide_t


class RealtimeSamplerEngine:
    """Mirrors tb303_rt.RealtimeEngine, but plays a sample (sax/brass/loaded WAV)."""

    def __init__(self, sr=44100, blocksize=256):
        self.sr = sr
        self.blocksize = blocksize
        self.params = np.zeros(NPARAMS, dtype=np.float64)
        self.state = np.zeros(NSTATE, dtype=np.float64)
        self.pat_f = np.full(64, -1.0)
        self.pat_a = np.zeros(64)
        self.pat_s = np.zeros(64)
        self.nsteps = 16
        self.sample = np.zeros(2, dtype=np.float64)
        self.base = 220.0
        self.level = 0.0
        self._lock = threading.Lock()
        self.stream = None
        d = {"cutoff": 0.5, "resonance": 0.2, "env_mod": 0.2, "decay": 0.4,
             "accent": 0.5, "bpm": 130, "distortion": 0.0, "volume": 0.9,
             "subdiv": 4, "gate_len": 0.6, "swing": 0.0, "tuning": 440}
        for k, v in d.items():
            self.set_param(k, v)
        self.set_param("playing", 0)

    _PIDX = {"cutoff": P_CUTOFF, "resonance": P_RESO, "env_mod": P_ENVMOD,
             "decay": P_DECAY, "accent": P_ACCENT, "bpm": P_BPM, "distortion": P_DIST,
             "volume": P_VOL, "subdiv": P_SUBDIV, "gate_len": P_GATE, "swing": P_SWING,
             "tuning": P_TUNING}

    def set_param(self, name, value):
        if name == "playing":
            self.params[P_PLAY] = 1.0 if value else 0.0
        elif name in self._PIDX:
            self.params[self._PIDX[name]] = float(value)

    def set_sample(self, samples, base_freq):
        s = np.ascontiguousarray(np.asarray(samples, dtype=np.float64))
        if s.size < 2:
            s = np.zeros(2, dtype=np.float64)
        with self._lock:
            self.sample = s
            self.base = float(base_freq) if base_freq and base_freq > 0 else 220.0

    def set_pattern(self, steps, tuning=None):
        with self._lock:
            self.nsteps = max(1, min(64, len(steps)))
            for i in range(64):
                if i < len(steps):
                    s = steps[i]
                    note, acc, sld = parse_step(s) if isinstance(s, str) else s
                    self.pat_f[i] = note_to_freq(note, 440.0) if note else -1.0
                    self.pat_a[i] = 1.0 if acc else 0.0
                    self.pat_s[i] = 1.0 if sld else 0.0
                else:
                    self.pat_f[i] = -1.0; self.pat_a[i] = 0.0; self.pat_s[i] = 0.0

    def set_playing(self, on):
        if on:
            self.state[S_INIT] = 0.0
        self.set_param("playing", 1 if on else 0)

    def preview(self, note, dur=0.5):
        f = note_to_freq(note, 440.0) * (self.params[P_TUNING] / 440.0) if note else 0.0
        if f > 0.0:
            self.state[S_PREVF] = f
            self.state[S_PREVPOS] = 0.0
            self.state[S_PREVN] = dur * self.sr

    def _callback(self, outdata, frames, time_info, status):
        buf = np.empty(frames, dtype=np.float64)
        with self._lock:
            synth_block(buf, frames, self.state, self.params,
                        self.pat_f, self.pat_a, self.pat_s, self.nsteps, float(self.sr),
                        self.sample, self.sample.size, self.base)
        np.clip(buf, -1.0, 1.0, out=buf)
        peak = float(np.abs(buf).max())
        self.level = peak if peak > self.level else self.level * 0.82
        outdata[:, 0] = buf
        outdata[:, 1] = buf

    def get_level(self):
        return self.level

    def start(self):
        if self.stream is None:
            self.stream = sd.OutputStream(samplerate=self.sr, channels=2,
                                          blocksize=self.blocksize, dtype="float32",
                                          callback=self._callback)
            self.stream.start()

    def stop(self):
        if self.stream is not None:
            self.stream.stop(); self.stream.close(); self.stream = None


def reference_sample(name, sr=44100):
    """Return (samples, base_freq) for a built-in synthetic voice, pre-rendered once
    at a comfortable base note so the real-time engine can just transpose it."""
    import instruments
    base = 220.0
    if name in instruments.BUILTIN:
        s = instruments.BUILTIN[name](base, 1.8, False, sr)
    else:
        s = np.zeros(2)
    return np.ascontiguousarray(s.astype(np.float64)), base


if __name__ == "__main__":
    # standalone smoke test: pre-render a sax, play the demo in real time, sweep cutoff
    import time
    import instruments
    eng = RealtimeSamplerEngine()
    smp, base = reference_sample("Sax")
    eng.set_sample(smp, base)
    eng.set_pattern(DEMO_PATTERN)
    eng.start()
    eng.set_playing(True)
    print("real-time sax demo (cutoff sweep)... Ctrl+C to stop")
    try:
        for k in range(200):
            eng.set_param("cutoff", 0.25 + 0.6 * (0.5 + 0.5 * math.sin(k / 20.0)))
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    eng.set_playing(False); eng.stop()
