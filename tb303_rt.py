"""
tb303_rt.py — moteur TB-303 *temps reel* (callback sounddevice + DSP compilee Numba).

Contrairement a tb303.py (rendu hors-ligne puis boucle), ici l'audio est genere
en continu, bloc par bloc, dans un callback. Les parametres (potards) et le pattern
sont lus a chaque bloc : tourner un potard s'entend immediatement, sans redemarrer
la boucle. La meme chaine DSP que tb303.py est utilisee (oscillateur PolyBLEP ->
filtre ladder 4 etages sortie 3e pole ~18 dB/oct, contre-reaction 4e pole + tanh).

Dependances machine :  pip install numba sounddevice   (+ libportaudio2 sous Linux :
                       sudo apt install libportaudio2)

Test rapide (joue la demo en temps reel et balaie le cutoff pour prouver le live) :
    python3 tb303_rt.py
"""
import math
import threading
import os
import numpy as np

# WSL/WSLg : router l'audio vers PulseAudio sans avoir a exporter la variable a la main
if os.path.exists("/mnt/wslg/PulseServer"):
    os.environ.setdefault("PULSE_SERVER", "unix:/mnt/wslg/PulseServer")

try:
    from numba import njit
    _HAS_NUMBA = True
except Exception:                     # repli : marche mais risque de saccader
    _HAS_NUMBA = False
    def njit(*a, **k):
        def deco(f): return f
        return (deco if (a and callable(a[0])) is False else a[0])

# index des parametres partages (ecrits par le GUI, lus par le callback)
P_CUTOFF, P_RESO, P_ENVMOD, P_DECAY, P_ACCENT, P_BPM = 0, 1, 2, 3, 4, 5
P_DIST, P_VOL, P_WAVE, P_SUBDIV, P_GATE, P_SWING, P_TUNING, P_PLAY = 6, 7, 8, 9, 10, 11, 12, 13
NPARAMS = 14

# index de l'etat persistant
S_PHASE, S_S1, S_S2, S_S3, S_S4, S_FENV, S_AENV = 0, 1, 2, 3, 4, 5, 6
S_FREQ, S_STEP, S_SIS, S_GATE, S_ACC, S_PREVSL, S_INIT, S_GLIDE = 7, 8, 9, 10, 11, 12, 13, 14
S_PREVF, S_PREVN = 15, 16          # audition d'une note (frequence, echantillons restants)
NSTATE = 18


@njit(cache=True, fastmath=True)
def _blep(t, dt):
    if t < dt:
        t = t / dt
        return t + t - t * t - 1.0
    elif t > 1.0 - dt:
        t = (t - 1.0) / dt
        return t * t + t + t + 1.0
    return 0.0


@njit(cache=True, fastmath=True)
def synth_block(out, frames, st, pr, pat_f, pat_a, pat_s, nsteps, sr):
    cutoff = pr[P_CUTOFF]; reso = pr[P_RESO]; envmod = pr[P_ENVMOD]
    decay = pr[P_DECAY]; accent = pr[P_ACCENT]; bpm = pr[P_BPM]
    dist = pr[P_DIST]; vol = pr[P_VOL]; wave = pr[P_WAVE]
    subdiv = pr[P_SUBDIV]; gate_len = pr[P_GATE]; swing = pr[P_SWING]
    tuning = pr[P_TUNING]; playing = pr[P_PLAY]

    res_amt = reso * 4.2
    base_fc = 30.0 * (10000.0 / 30.0) ** cutoff
    tau = 0.04 + decay * 1.6
    fdec = math.exp(-1.0 / (sr * tau))
    a_atk = 1.0 - math.exp(-1.0 / (sr * 0.003))
    a_rel = 1.0 - math.exp(-1.0 / (sr * 0.008))
    glide = 1.0 - math.exp(-1.0 / (sr * 0.035))         # portamento ~35 ms
    step_dur = sr * 60.0 / max(bpm, 1.0) / max(subdiv, 1.0)
    tun = tuning / 440.0

    phase = st[S_PHASE]; s1 = st[S_S1]; s2 = st[S_S2]; s3 = st[S_S3]; s4 = st[S_S4]
    fenv = st[S_FENV]; aenv = st[S_AENV]; freq = st[S_FREQ]
    step = int(st[S_STEP]); sis = st[S_SIS]; gate = st[S_GATE]
    acc = st[S_ACC]; prevsl = st[S_PREVSL]; init = st[S_INIT]; glide_t = st[S_GLIDE]

    if playing < 0.5:
        prevn = st[S_PREVN]
        if prevn > 0.5:                       # audition d'une note (clic clavier a l'arret)
            prevf = st[S_PREVF]
            rel_at = 0.12 * sr
            for i in range(frames):
                if prevn <= 0.5:
                    out[i] = 0.0
                    continue
                g_on = 1.0 if prevn > rel_at else 0.0
                dt = prevf / sr
                if wave < 0.5:
                    osc = 2.0 * phase - 1.0 - _blep(phase, dt)
                else:
                    p2 = phase + 0.5
                    if p2 >= 1.0:
                        p2 -= 1.0
                    osc = (1.0 if phase < 0.5 else -1.0) + _blep(phase, dt) - _blep(p2, dt)
                phase += dt
                if phase >= 1.0:
                    phase -= 1.0
                aenv += (a_atk if g_on > aenv else a_rel) * (g_on - aenv)
                fenv *= fdec
                fc = base_fc * (2.0 ** (envmod * 6.0 * fenv))
                if fc > 16000.0:
                    fc = 16000.0
                if fc < 20.0:
                    fc = 20.0
                gi = 1.0 - math.exp(-2.0 * math.pi * fc / sr)
                inp = math.tanh(osc - res_amt * s4)
                s1 += gi * (inp - s1); s2 += gi * (s1 - s2)
                s3 += gi * (s2 - s3); s4 += gi * (s3 - s4)
                out[i] = math.tanh(s3 * 1.9 * aenv * vol)
                prevn -= 1.0
            st[S_PHASE] = phase; st[S_S1] = s1; st[S_S2] = s2; st[S_S3] = s3; st[S_S4] = s4
            st[S_FENV] = fenv; st[S_AENV] = aenv; st[S_PREVN] = prevn
        else:
            for i in range(frames):
                out[i] = 0.0
            st[S_PHASE] = phase; st[S_FENV] = fenv; st[S_AENV] = 0.0
        return

    for i in range(frames):
        # --- sequenceur ---
        sd = step_dur * (1.0 + swing) if (step % 2 == 0) else step_dur * (1.0 - swing)
        if init < 0.5 or sis >= sd:
            if init >= 0.5:
                step = (step + 1) % nsteps
                sis -= sd
            else:
                step = 0; sis = 0.0; init = 1.0
            f = pat_f[step]
            if f <= 0.0:                       # silence
                gate = 0.0
            else:
                tgt = f * tun
                glide_t = tgt
                if prevsl > 0.5:               # legato : on glisse, pas de re-attaque
                    pass
                else:
                    freq = tgt
                    fenv = 1.0                 # re-declenche l'enveloppe de filtre
                gate = 1.0
                acc = pat_a[step]
            prevsl = pat_s[step]

        # portamento
        freq += (glide_t - freq) * glide

        # gate (longueur de note ; slide = legato sur tout le pas)
        gate_samps = sd if prevsl > 0.5 else gate_len * sd
        g_on = 1.0 if (gate > 0.5 and sis < gate_samps) else 0.0

        # --- oscillateur PolyBLEP ---
        dt = freq / sr
        if wave < 0.5:                          # saw
            osc = 2.0 * phase - 1.0 - _blep(phase, dt)
        else:                                   # square
            p2 = phase + 0.5
            if p2 >= 1.0:
                p2 -= 1.0
            osc = (1.0 if phase < 0.5 else -1.0) + _blep(phase, dt) - _blep(p2, dt)
        phase += dt
        if phase >= 1.0:
            phase -= 1.0

        # --- enveloppes ---
        acc_boost = 1.0 + accent * acc
        target = g_on * acc_boost
        aenv += (a_atk if target > aenv else a_rel) * (target - aenv)
        fenv *= fdec

        # --- filtre ladder type 303 ---
        fc = base_fc * (2.0 ** (envmod * 6.0 * fenv + accent * acc * 1.5))
        if fc > 16000.0:
            fc = 16000.0
        if fc < 20.0:
            fc = 20.0
        gi = 1.0 - math.exp(-2.0 * math.pi * fc / sr)
        inp = math.tanh(osc - res_amt * s4)
        s1 += gi * (inp - s1)
        s2 += gi * (s1 - s2)
        s3 += gi * (s2 - s3)
        s4 += gi * (s3 - s4)
        y = s3 * 1.9 * aenv

        if dist > 0.0:
            drive = 1.0 + dist * 18.0
            y = math.tanh(y * drive) / math.tanh(drive) if drive > 0 else y

        out[i] = math.tanh(y * vol)         # limiteur doux : borne sans ecreter dur
        sis += 1.0

    st[S_PHASE] = phase; st[S_S1] = s1; st[S_S2] = s2; st[S_S3] = s3; st[S_S4] = s4
    st[S_FENV] = fenv; st[S_AENV] = aenv; st[S_FREQ] = freq
    st[S_STEP] = step; st[S_SIS] = sis; st[S_GATE] = gate
    st[S_ACC] = acc; st[S_PREVSL] = prevsl; st[S_INIT] = init; st[S_GLIDE] = glide_t


_NOTES = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "F": 5,
          "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11}


def note_to_freq(name, tuning=440.0):
    name = name.strip()
    i = 0
    while i < len(name) and (name[i].isalpha() or name[i] == "#"):
        i += 1
    key = name[:i].upper().replace("♯", "#")
    octave = int(name[i:]) if name[i:] else 4
    semis = _NOTES.get(key, 0) + (octave - 4) * 12 - 9    # A4 = 440
    return tuning * (2.0 ** (semis / 12.0))


def parse_step(s):
    s = s.strip()
    if s in (".", "", "rest", "-"):
        return (None, False, False)
    acc = "+" in s
    sld = "~" in s
    name = s.replace("+", "").replace("~", "")
    return (name, acc, sld)


class RealtimeEngine:
    """Moteur audio temps reel. Le GUI appelle set_param / set_pattern / set_playing."""

    def __init__(self, sr=44100, blocksize=256):
        self.sr = sr
        self.blocksize = blocksize
        self.params = np.zeros(NPARAMS, dtype=np.float64)
        self.state = np.zeros(NSTATE, dtype=np.float64)
        self.pat_f = np.full(64, -1.0)
        self.pat_a = np.zeros(64)
        self.pat_s = np.zeros(64)
        self.nsteps = 16
        self._lock = threading.Lock()
        self.stream = None
        # valeurs par defaut
        d = {"cutoff": 0.4, "resonance": 0.5, "env_mod": 0.5, "decay": 0.4,
             "accent": 0.5, "bpm": 130, "distortion": 0.0, "volume": 0.9,
             "waveform": "saw", "subdiv": 4, "gate_len": 0.55, "swing": 0.0, "tuning": 440}
        for k, v in d.items():
            self.set_param(k, v)
        self.set_param("playing", 0)

    _PIDX = {"cutoff": P_CUTOFF, "resonance": P_RESO, "env_mod": P_ENVMOD,
             "decay": P_DECAY, "accent": P_ACCENT, "bpm": P_BPM, "distortion": P_DIST,
             "volume": P_VOL, "subdiv": P_SUBDIV, "gate_len": P_GATE, "swing": P_SWING,
             "tuning": P_TUNING}

    def set_param(self, name, value):
        if name == "waveform":
            self.params[P_WAVE] = 0.0 if str(value).startswith("s") and value != "square" else 1.0
            self.params[P_WAVE] = 0.0 if value == "saw" else 1.0
        elif name == "playing":
            self.params[P_PLAY] = 1.0 if value else 0.0
        elif name in self._PIDX:
            self.params[self._PIDX[name]] = float(value)

    def set_pattern(self, steps, tuning=None):
        """steps : liste de 16 chaines ('C2', 'C2+', 'C2~', '.') ou tuples (note,acc,slide)."""
        tun = self.params[P_TUNING] if tuning is None else tuning
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
            self.state[S_INIT] = 0.0            # repart au pas 0
        self.set_param("playing", 1 if on else 0)

    def preview(self, note, dur=0.45):
        """Joue une note ponctuelle (audition au clic clavier), meme a l'arret."""
        f = note_to_freq(note, 440.0) * (self.params[P_TUNING] / 440.0) if note else 0.0
        if f > 0.0:
            self.state[S_PREVF] = f
            self.state[S_FENV] = 1.0
            self.state[S_PREVN] = dur * self.sr

    def _callback(self, outdata, frames, time_info, status):
        buf = np.empty(frames, dtype=np.float64)
        with self._lock:
            synth_block(buf, frames, self.state, self.params,
                        self.pat_f, self.pat_a, self.pat_s, self.nsteps, float(self.sr))
        np.clip(buf, -1.0, 1.0, out=buf)
        outdata[:, 0] = buf
        outdata[:, 1] = buf

    def start(self):
        import sounddevice as sd
        if self.stream is None:
            self.stream = sd.OutputStream(samplerate=self.sr, channels=2,
                                          blocksize=self.blocksize, dtype="float32",
                                          callback=self._callback)
            self.stream.start()

    def stop(self):
        if self.stream is not None:
            self.stream.stop(); self.stream.close(); self.stream = None


DEMO_PATTERN = ["C2", "C2~", "C3", "C2+", "D#2", "C2~", "C3", "A#1",
                "C2", "G2~", "C3+", "C2", "D#2", "C2", "A#1~", "C2+"]


def _demo():
    import time
    eng = RealtimeEngine()
    eng.set_pattern(DEMO_PATTERN)
    eng.set_param("resonance", 0.85)
    eng.set_param("env_mod", 0.6)
    eng.set_param("bpm", 130)
    eng.start()
    eng.set_playing(True)
    print("Lecture temps reel — balayage du CUTOFF en direct (Ctrl+C pour quitter)...")
    try:
        t0 = time.time()
        while time.time() - t0 < 12:
            x = (time.time() - t0) / 12.0
            eng.set_param("cutoff", 0.18 + 0.55 * (0.5 - 0.5 * math.cos(2 * math.pi * x * 2)))
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        eng.set_playing(False); time.sleep(0.1); eng.stop()
        print("fini.")


if __name__ == "__main__":
    _demo()
