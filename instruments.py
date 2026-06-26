"""
instruments.py - non-303 voices for TB-303 Studio: a simple Sampler (load a WAV and
play it pitched per step) plus built-in synthetic instruments (sax, brass).

Used by the studio when the chosen instrument isn't the TB-303 synth. Pure NumPy
(SciPy optional, only for nicer filtering); renders a whole pattern to a buffer that
the studio loops (pygame) and exports (WAV).
"""
import wave
import numpy as np

try:
    from scipy.signal import butter, lfilter
    _HAS_SCIPY = True
except Exception:
    _HAS_SCIPY = False

from tb303 import note_to_freq, apply_play_mode

SR = 44100
_NOTES = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "F": 5,
          "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11}


# ---------------------------------------------------------------- helpers
def _bandpass(x, f, Q, sr=SR):
    if not _HAS_SCIPY:
        return x
    w = f / (sr / 2)
    lo, hi = max(0.01, w / (1 + 0.5 / Q)), min(0.99, w * (1 + 0.5 / Q))
    b, a = butter(2, [lo, hi], btype="band")
    return lfilter(b, a, x)


def _adsr(n, sr, atk=0.02, rel=0.06, curve=1.4):
    env = np.ones(n)
    a = min(int(atk * sr), n // 2)
    r = min(int(rel * sr), n // 2)
    if a > 0:
        env[:a] = np.linspace(0, 1, a) ** curve
    if r > 0:
        env[-r:] = np.linspace(1, 0, r)
    return env


def load_wav(path, sr=SR):
    """Load a WAV as mono float (resampled to sr by linear interpolation)."""
    w = wave.open(path, "rb")
    fr, ch, n, sw = w.getframerate(), w.getnchannels(), w.getnframes(), w.getsampwidth()
    raw = w.readframes(n); w.close()
    dt = {1: np.int8, 2: np.int16, 4: np.int32}[sw]
    a = np.frombuffer(raw, dtype=dt).astype(np.float64)
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    a /= (2 ** (8 * sw - 1))
    if fr != sr:
        t = np.linspace(0, len(a) / fr, int(len(a) / fr * sr), endpoint=False)
        a = np.interp(t, np.arange(len(a)) / fr, a)
    return a


def detect_f0(a, sr=SR, lo=50, hi=1000):
    """Rough fundamental detection (autocorrelation) for a sample's base pitch."""
    x = a[: int(0.5 * sr)] if len(a) > sr // 2 else a
    x = x - x.mean()
    if np.sqrt((x ** 2).mean()) < 1e-4:
        return 220.0
    c = np.correlate(x, x, "full")[len(x) - 1:]
    klo, khi = int(sr / hi), int(sr / lo)
    if khi >= len(c):
        return 220.0
    k = klo + int(np.argmax(c[klo:khi]))
    return sr / k if k > 0 else 220.0


# ---------------------------------------------------------------- synthetic sax
def synth_sax(freq, dur, accent=False, sr=SR):
    n = max(1, int(dur * sr))
    t = np.arange(n) / sr
    vib = 1 + 0.004 * np.sin(2 * np.pi * 5.5 * t)
    phase = 2 * np.pi * np.cumsum(freq * vib) / sr
    src = 0.6 * (2 * (phase / (2 * np.pi) % 1) - 1) + 0.4 * np.sign(np.sin(phase)) * 0.5
    body = (1.0 * _bandpass(src, 700, 4) + 0.7 * _bandpass(src, 1300, 5)
            + 0.5 * _bandpass(src, 2600, 6) + 0.25 * src)
    breath = _bandpass(np.random.randn(n), 2500, 1.5) * (np.exp(-t * 8) * 0.6 + 0.05)
    sig = np.tanh((body + breath) * (1.9 if accent else 1.6))
    sig *= _adsr(n, sr, atk=0.035, rel=0.08)
    m = np.max(np.abs(sig)) + 1e-9
    return sig / m * (0.95 if accent else 0.8)


def synth_brass(freq, dur, accent=False, sr=SR):
    n = max(1, int(dur * sr))
    t = np.arange(n) / sr
    phase = 2 * np.pi * freq * t
    # simple FM for a brassy tone, index swells in
    idx = (2.5 if accent else 1.8) * (1 - np.exp(-t * 12))
    sig = np.sin(phase + idx * np.sin(phase))
    sig = _bandpass(sig, 1200, 2) * 0.7 + sig * 0.3
    sig = np.tanh(sig * 1.4)
    sig *= _adsr(n, sr, atk=0.025, rel=0.07)
    m = np.max(np.abs(sig)) + 1e-9
    return sig / m * (0.95 if accent else 0.8)


# ---------------------------------------------------------------- sampler
class Sampler:
    def __init__(self, samples, base_freq=None, sr=SR):
        self.sr = sr
        self.s = np.asarray(samples, dtype=np.float64)
        self.base = base_freq or detect_f0(self.s, sr)

    @classmethod
    def from_wav(cls, path, base_freq=None, sr=SR):
        a = load_wav(path, sr)
        return cls(a, base_freq, sr)

    def note(self, freq, dur, accent=False):
        n = max(1, int(dur * self.sr))
        ratio = freq / self.base                       # pitch shift = resample
        idx = np.arange(n) * ratio
        if len(self.s) == 0:
            return np.zeros(n)
        # loop the source if the (resampled) note is longer than the sample
        src_idx = idx % (len(self.s) - 1)
        out = np.interp(src_idx, np.arange(len(self.s)), self.s)
        out *= _adsr(n, self.sr, atk=0.005, rel=0.04, curve=1.0)
        return out * (1.15 if accent else 0.9)


# ---------------------------------------------------------------- pattern render
def render_pattern(steps, voice, bpm=130, subdiv=4, swing=0.0, play_mode="forward",
                   repeats=1, gate_len=0.6, tuning=440.0, sr=SR):
    """voice: callable(freq, dur, accent) -> mono array (synth_sax/brass or Sampler.note)."""
    seq = apply_play_mode([dict(s) for s in steps], play_mode) * repeats
    if not seq:
        return np.zeros((0, 2))
    step = 60.0 / bpm / max(subdiv, 1)
    swing = max(0.0, min(0.66, swing))
    total = int(len(seq) * step * sr) + sr
    buf = np.zeros(total)
    pos = 0.0
    for i, st in enumerate(seq):
        sd = step * (1 + swing) if i % 2 == 0 else step * (1 - swing)
        if st.get("note") and st["note"] not in (".", ""):
            f = note_to_freq(st["note"], tuning)
            dur = sd * (1.0 if st.get("slide") else gate_len) + 0.02
            note = voice(f, dur, st.get("accent", False))
            a = int(pos * sr)
            buf[a:a + len(note)] += note[: max(0, total - a)]
        pos += sd
    end = int(pos * sr)
    buf = buf[:end]
    m = np.max(np.abs(buf)) + 1e-9
    if m > 1.0:
        buf /= m
    return np.column_stack([buf, buf])


BUILTIN = {"Sax": synth_sax, "Brass": synth_brass}
