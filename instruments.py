"""
instruments.py - non-303 voices for TB-303 Studio: a simple Sampler (load a WAV and
play it pitched per step) plus built-in synthetic instruments (sax, brass).

Used by the studio when the chosen instrument isn't the TB-303 synth. Pure NumPy
(SciPy optional, only for nicer filtering); renders a whole pattern to a buffer that
the studio loops (pygame) and exports (WAV).
"""
import os
import wave
import shutil
import tempfile
import subprocess
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


def _resample(a, fr, sr):
    if fr and fr != sr:
        t = np.linspace(0, len(a) / fr, int(len(a) / fr * sr), endpoint=False)
        a = np.interp(t, np.arange(len(a)) / fr, a)
    return a


def _load_wav_builtin(path, sr=SR):
    """Read a WAV of any common depth (8/16/24/32-bit PCM or float32) as mono float.
    Used as the no-dependency fallback; the stdlib wave module cannot read 24-bit."""
    import struct
    b = open(path, "rb").read()
    if b[:4] != b"RIFF" or b[8:12] != b"WAVE":
        raise ValueError("not a WAV file")
    fmt = ch = fr = bits = None
    data = None
    i = 12
    while i + 8 <= len(b):
        cid = b[i:i + 4]
        sz = struct.unpack("<I", b[i + 4:i + 8])[0]
        body = b[i + 8:i + 8 + sz]
        if cid == b"fmt ":
            fmt, ch, fr, _br, _ba, bits = struct.unpack("<HHIIHH", body[:16])
        elif cid == b"data":
            data = body
        i += 8 + sz + (sz & 1)
    if data is None or fmt is None:
        raise ValueError("WAV missing fmt/data chunk")
    raw = np.frombuffer(data, dtype=np.uint8)
    if bits == 8:
        a = (raw.astype(np.float64) - 128) / 128.0
    elif bits == 16:
        a = np.frombuffer(data, dtype="<i2").astype(np.float64) / 32768.0
    elif bits == 24:
        v = raw[: (len(raw) // 3) * 3].reshape(-1, 3)
        x = (v[:, 0].astype(np.int32) | (v[:, 1].astype(np.int32) << 8)
             | (v[:, 2].astype(np.int32) << 16))
        x = np.where(x & 0x800000, x - 0x1000000, x)
        a = x.astype(np.float64) / (2 ** 23)
    elif bits == 32 and fmt == 3:
        a = np.frombuffer(data, dtype="<f4").astype(np.float64)
    elif bits == 32:
        a = np.frombuffer(data, dtype="<i4").astype(np.float64) / (2 ** 31)
    else:
        raise ValueError(f"unsupported WAV depth: {bits}-bit (fmt {fmt})")
    if ch and ch > 1:
        a = a[: (len(a) // ch) * ch].reshape(-1, ch).mean(axis=1)
    return _resample(a, fr, sr)


def _ffmpeg_decode(path, sr=SR):
    """Decode any audio file to mono float via ffmpeg (mp3, flac, ogg, m4a, aiff...)."""
    exe = shutil.which("ffmpeg")
    if not exe:
        return None
    tmp = tempfile.mktemp(suffix=".wav")
    try:
        subprocess.run([exe, "-y", "-i", path, "-ac", "1", "-ar", str(sr),
                        "-c:a", "pcm_s16le", "-f", "wav", tmp],
                       capture_output=True, check=True)
        return _load_wav_builtin(tmp, sr)
    except Exception:
        return None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def load_audio(path, sr=SR):
    """Load *any* audio format as mono float at sr.
    Order: soundfile (WAV/FLAC/OGG/AIFF/...) -> ffmpeg (mp3/m4a/anything) -> builtin WAV."""
    try:
        import soundfile as sf
        a, fr = sf.read(path, always_2d=True, dtype="float64")
        return _resample(a.mean(axis=1), fr, sr)
    except ImportError:
        pass
    except Exception:
        pass
    a = _ffmpeg_decode(path, sr)
    if a is not None:
        return a
    return _load_wav_builtin(path, sr)


# kept for compatibility (Sampler.from_wav and existing callers)
def load_wav(path, sr=SR):
    return load_audio(path, sr)


def _write_wav16(audio, path, sr=SR):
    a = np.clip(np.asarray(audio, dtype=np.float64), -1, 1)
    ch = 2 if (a.ndim == 2 and a.shape[1] == 2) else 1
    w = wave.open(path, "w")
    w.setnchannels(ch); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes((a * 32767).astype("<i2").tobytes())
    w.close()


def write_audio(audio, path, sr=SR):
    """Write audio to *any* format chosen by extension.
    WAV is written natively; FLAC/OGG/AIFF via soundfile; mp3/anything via ffmpeg."""
    ext = os.path.splitext(path)[1].lower()
    if ext in ("", ".wav"):
        _write_wav16(audio, path, sr)
        return
    try:
        import soundfile as sf
        sf.write(path, np.clip(np.asarray(audio), -1, 1), sr)
        return
    except ImportError:
        pass
    except Exception:
        pass
    exe = shutil.which("ffmpeg")
    if exe:
        tmp = tempfile.mktemp(suffix=".wav")
        _write_wav16(audio, tmp, sr)
        try:
            subprocess.run([exe, "-y", "-i", tmp, path], capture_output=True, check=True)
            return
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    raise RuntimeError(f"to export {ext}, install soundfile or ffmpeg")


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
def _biquad_lp(fc, Q, sr):
    w0 = 2 * np.pi * min(fc, sr * 0.45) / sr
    cosw, sinw = np.cos(w0), np.sin(w0)
    alpha = sinw / (2 * max(0.5, Q))
    b0 = (1 - cosw) / 2; b1 = 1 - cosw; b2 = (1 - cosw) / 2
    a0 = 1 + alpha; a1 = -2 * cosw; a2 = 1 - alpha
    return (np.array([b0 / a0, b1 / a0, b2 / a0]), np.array([1.0, a1 / a0, a2 / a0]))


def _reso_filter(note, cutoff, resonance, env_mod, decay, distortion, accent, sr=SR):
    """Run a voice through a 303-style resonant low-pass swept by a per-note envelope,
    plus optional tanh distortion. Makes CUT OFF / RESONANCE / ENV MOD / DECAY / DIST
    affect sampled or synthetic instruments too. cutoff=None -> bypass."""
    if cutoff is None:
        return note
    n = len(note)
    if n < 8:
        return note
    if not _HAS_SCIPY:                                # no resonance without scipy
        out = note
        if distortion > 0:
            d = 1 + distortion * 6
            out = np.tanh(out * d) / np.tanh(d)
        return out
    from scipy.signal import lfilter, lfilter_zi
    Q = 0.6 + resonance * 7.0
    tau = 0.03 + decay * 0.6
    acc = 0.18 if accent else 0.0
    blk = max(128, int(0.012 * sr))                  # ~12 ms blocks for the sweep
    out = np.empty_like(note)
    zi = None
    t = 0.0
    for s in range(0, n, blk):
        e = np.exp(-t / tau)
        cn = min(1.0, max(0.0, cutoff + env_mod * e + acc))
        fc = 180.0 + 11800.0 * (cn ** 2)             # mostly open mid/high, darkens low
        b, a = _biquad_lp(fc, Q, sr)
        seg = note[s:s + blk]
        if zi is None:
            zi = lfilter_zi(b, a) * seg[0]
        y, zi = lfilter(b, a, seg, zi=zi)
        out[s:s + len(seg)] = y
        t += len(seg) / sr
    if distortion > 0:
        d = 1 + distortion * 6
        out = np.tanh(out * d) / np.tanh(d)
    return out


def render_pattern(steps, voice, bpm=130, subdiv=4, swing=0.0, play_mode="forward",
                   repeats=1, gate_len=0.6, tuning=440.0, sr=SR,
                   cutoff=None, resonance=0.0, env_mod=0.0, decay=0.5, distortion=0.0):
    """voice: callable(freq, dur, accent) -> mono array (synth_sax/brass or Sampler.note).
    If cutoff is given, each note is run through a resonant low-pass + distortion so the
    filter knobs act on the instrument too."""
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
            acc = st.get("accent", False)
            dur = sd * (1.0 if st.get("slide") else gate_len) + 0.02
            note = voice(f, dur, acc)
            note = _reso_filter(note, cutoff, resonance, env_mod, decay, distortion, acc, sr)
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
