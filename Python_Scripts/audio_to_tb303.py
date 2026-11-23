#!/usr/bin/env python3
"""Rebuild a TB-303 Studio pattern from a recorded bass line.

Lives in Python_Scripts, next to tb303.py and tb303_rt.py. The studio runs it for
File -> Import pattern from audio...; it also works on its own:

    python audio_to_tb303.py line.wav
    python audio_to_tb303.py track.mp3 --mix
    python audio_to_tb303.py line.mp3 --bpm 128 --start 0.24 -o line.tb303

Needs numpy, scipy and numba; no MIDI or audio device. Any audio format the studio
can read is accepted (WAV directly; MP3, FLAC, OGG... through the studio's decoder).
The audio must hold at least one 16-step loop of a single bass line. Step 1 is where
the sound begins (a note, or a beat of a mixed track), unless the attacks show it was
cut inside a note: the steps are then placed from the attacks and step 1 is the first
full step. --start picks another loop (when the line changes) or another step 1. With
--mix, the drums of a mixed extract are softened before the line is read; other
instruments still get in the way. Without it, the drums are softened all the same when
hi-hats, snares or claps are heard (--no-mix prevents it).

The tempo, swing, notes, slides, accents and tuning are read from the audio; the
sound knobs (cutoff, resonance, env mod, decay, accent, distortion, volume) are then
fitted by letting the studio's real-time engine play the pattern and comparing.
"""

import argparse
from dataclasses import dataclass
from pathlib import Path
import json
import sys

import numpy as np
from scipy import fft, ndimage, optimize, signal
from scipy.io import wavfile


SR = 44_100
STEPS = 16
BANKS = 8
SCALES = {"1/8": 2, "1/8T": 3, "1/16": 4, "1/16T": 6, "1/32": 8}
FIT_KEYS = ("cutoff", "resonance", "env_mod", "decay", "accent", "distortion", "volume")
FIT_BOUNDS = [(0.02, 0.88), (0, 1), (0, 1), (0, 1), (0, 1), (0, 1), (0.2, 1)]
LEVEL_WEIGHT = 0.15         # score per dB of loudness difference with the audio
NAME = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


@dataclass
class Grid:
    bpm: float
    start: float
    subdiv: int
    shuffle: float

    @property
    def step(self):
        return 60 / (self.bpm * self.subdiv)

    @property
    def duration(self):
        return STEPS * self.step

    @property
    def edges(self):
        indices = np.arange(STEPS + 1)
        return self.step * (indices + self.shuffle * (indices % 2))


def read_audio(path):
    """(audio scaled to a peak of 1, that peak in full-scale units)."""
    if path.suffix.lower() == ".wav":
        try:
            return read_wav(path)
        except ValueError:
            raise
        except Exception:
            pass                     # unusual WAV flavour: let the studio's decoder try
    import instruments               # the studio's decoder: soundfile, then ffmpeg
    audio = np.asarray(instruments.load_audio(str(path), SR), dtype=float)
    if not audio.size:
        raise ValueError("the audio file is empty or could not be decoded.")
    audio = audio - np.median(audio)
    peak = np.max(np.abs(audio), initial=0)
    if peak == 0:
        raise ValueError("the audio file is empty or silent.")
    return audio / peak, float(peak)


def read_wav(path):
    rate, raw = wavfile.read(path)
    if not raw.size:
        raise ValueError("the WAV is empty.")
    audio = np.nan_to_num(raw.astype(float), posinf=0., neginf=0.)
    full_scale = 1.0
    if raw.dtype.kind == "u":
        audio -= (np.iinfo(raw.dtype).max + 1) / 2
        full_scale = (np.iinfo(raw.dtype).max + 1) / 2
    elif raw.dtype.kind == "i":
        full_scale = np.iinfo(raw.dtype).max + 1
    if audio.ndim == 2:
        channels, audio = audio, audio.mean(axis=1)
        if np.linalg.norm(audio) < .1 * np.linalg.norm(channels[:, 0]):
            audio = channels[:, 0]          # channels in opposite phase: keep one
    audio -= np.median(audio)
    peak = np.max(np.abs(audio), initial=0)
    if peak == 0:
        raise ValueError("the WAV is empty or silent.")
    if rate != SR:
        ratio = np.gcd(rate, SR)
        audio = signal.resample_poly(audio, SR // ratio, rate // ratio)
    return audio / peak, float(peak / full_scale)


def envelope(audio, seconds=.005):
    return np.sqrt(np.maximum(0, ndimage.uniform_filter1d(audio ** 2, max(1, round(seconds * SR)))))


def track_rhythm(audio):
    hop = 128
    times = np.arange(0, len(audio), hop) / SR
    env = envelope(audio)[::hop]
    rises = np.maximum(0, np.diff(np.log(.035 + env), prepend=np.log(.035)))
    spikes = ndimage.gaussian_filter1d(rises, 0.8)
    indices, _ = signal.find_peaks(spikes, prominence=max(.015, np.max(spikes) * .07),
                                   distance=round(.042 * SR / hop))
    indices = indices[(times[indices] > .014) & (times[indices] < len(audio) / SR - .012)]
    _, _, z = signal.stft(audio, SR, nperseg=1536, noverlap=1536 - hop)
    idx = np.searchsorted(np.fft.rfftfreq(1536, 1 / SR), [0, 120, 230, 420, 800, 1800, 4000])
    p = np.add.reduceat(np.abs(z) ** 2, idx, axis=0)
    feature = np.log(.00009 + p)
    feature -= feature.mean(axis=1, keepdims=True)
    n = feature.shape[1]
    ac = fft.irfft(np.sum(np.abs(fft.rfft(feature, n=fft.next_fast_len(2 * n - 1))) ** 2,
                          axis=0), n=fft.next_fast_len(2 * n - 1))[:n]
    corr = ac / (ac[0] + 1e-12) * n / np.maximum(n - np.arange(n), n / 4)
    return times[indices], spikes[indices], np.arange(n) * hop / SR, corr


def first_sound(audio):
    """Time of the first sound (where step 1 starts when the audio is cut on a step)."""
    on = np.flatnonzero(envelope(audio) > .035)
    estimated = max(0, (int(on[0]) - .001 * SR) / SR) if len(on) else 0
    audible = np.flatnonzero(np.abs(audio) > .002)
    if len(audible) and abs(audible[0] / SR - estimated) < .012:
        estimated = audible[0] / SR
    return estimated if estimated > .025 else 0.


def opens_on_attack(audio, heard):
    """True when the audio opens on a note starting at `heard`, false when it was cut
    inside a note. After silence, the first sound is an attack. When sound is there
    from the first sample, a note that starts is quieter in its first 10 ms than in
    the next 20 (windows longer than half a period of a low note); a note cut in the
    middle is not."""
    if heard > 0:
        return True
    first = np.sqrt(np.mean(audio[:round(.010 * SR)] ** 2))
    then = np.sqrt(np.mean(audio[round(.010 * SR):round(.030 * SR)] ** 2))
    return first < .6 * then


MOVE_FROM_FIRST_SOUND = .05   # alignment gain needed to start the steps away from the first sound


def grid_alignment(t, weights, periods, mode):
    """How well attacks at times t fall on grids of these periods (step lengths).

    Returns the straight alignment, the swung alignment (even steps on the grid, odd
    steps late) and, for each, the phase of the grid in steps. mode "fixed": the grid
    starts at t = 0. "late": t = 0 is a late (odd) step of a swung grid. "free": the
    best phase is searched, since the audio may have been cut anywhere in a step."""
    straight = np.arange(24) / 24 if mode == "free" else np.zeros(1)
    swung = {"free": np.arange(48) / 24,
             "late": 1 - np.arange(.04, .35, .02)}.get(mode, np.zeros(1))
    root = np.sqrt(weights)
    total = root.sum()
    results = [np.empty(len(periods)) for _ in range(4)]
    for a in range(0, len(periods), 128):
        cycles = t[None, :] / periods[a:a + 128, None]
        phase = cycles[:, None, :] - straight[None, :, None]
        distance = np.abs(phase - np.rint(phase))
        score = (np.exp(-.5 * (distance / .085) ** 2) @ root) / total
        best = np.argmax(score, axis=1)
        results[0][a:a + 128] = score[np.arange(len(best)), best]
        results[1][a:a + 128] = straight[best]
        phase = cycles[:, None, :] - swung[None, :, None]
        halves = phase / 2
        even = np.abs(halves - np.rint(halves)) * 2
        odd = (phase % 2) - 1
        score = (np.maximum(np.exp(-.5 * (even / .085) ** 2),
                            .70 * np.exp(-.5 * (np.clip(abs(odd - .19) - .15, 0, None) / .09) ** 2))
                 @ root) / total
        best = np.argmax(score, axis=1)
        results[2][a:a + 128] = score[np.arange(len(best)), best]
        results[3][a:a + 128] = swung[best]
    return results


def detect_grid(audio, subdiv, start=None, bpm=None, shuffle=None):
    heard = first_sound(audio)
    anchored = start is None and opens_on_attack(audio, heard)
    if anchored:
        start = heard                     # a note starts there: it begins a step, as cut
    free = start is None                  # cut inside a note: place the steps from the attacks
    mode = "free" if free else "fixed"
    origin = heard if free else start
    available = len(audio) / SR - origin
    if available < 16 * 60 / (200 * subdiv) - .025:
        raise ValueError("the audio is too short for 16 steps at this scale.")
    onsets, weights, lag_times, ac = track_rhythm(audio[round(origin * SR):])
    if len(weights):
        # Weak rises are mostly ripples in the decay of a low note, not attacks: left
        # in, they make a grid twice as fine look better (slow lines read at double tempo).
        strong = weights >= .25 * np.quantile(weights, .9)
        onsets, weights = onsets[strong], weights[strong]
    if len(onsets) < 4:
        if bpm is None:
            raise ValueError("ambiguous tempo: give it with --bpm.")
        free, anchored, start, mode = False, False, origin, "fixed"   # too few attacks to place the steps
    t = onsets - .003
    if bpm is None:
        periods = 60 / (np.arange(60.0, 200.01, .05) * subdiv)
        counts = np.arange(1, int(available / periods.min() / STEPS) + 2)
        exact = available / (STEPS * counts)
        periods = np.sort(np.r_[periods, exact[(exact >= periods.min()) & (exact <= periods.max())]])
        periods = periods[STEPS * periods <= available + .022]
        steps_hit = np.clip(len(onsets) * periods / available, 0, 1.0)
        loop = STEPS * periods
        rep = np.clip((np.interp(loop, lag_times, ac) - .67) / .30, 0, 1)
        rep *= np.clip((available / loop - 1) / .65, 0, 1)
        near_duration = np.abs(available - np.maximum(1, np.round(available / loop)) * loop)
        duration_bonus = np.exp(-.5 * (near_duration / .023) ** 2)
        rest = .21 * steps_hit + .56 * rep + .13 * duration_bonus
        # Attacks on even steps stay on the grid even with swing.
        align, phase, swing_alignment, swing_phase = grid_alignment(t, weights, periods, mode)
        score = np.maximum(align, swing_alignment) + rest
        if free:
            # Sound from the first sample on: a cut inside a note, or a mix (drums, pads)
            # cut on a beat. Keep the first sound as a step start unless the attacks
            # clearly sit elsewhere: in a mix, a second set of rises (the bass coming
            # back after each kick, echoes) can pull a searched phase off the beat.
            fixed = grid_alignment(t, weights, periods, "fixed")
            fixed_score = np.maximum(fixed[0], fixed[2]) + rest
            best = int(np.argmax(score))
            if score[best] - fixed_score[best] <= MOVE_FROM_FIRST_SOUND:
                free, anchored, start, mode = False, True, heard, "fixed"
                align, phase, swing_alignment, swing_phase = fixed
                score = fixed_score
        i = int(np.argmax(score))
        late = False
        if anchored:
            # Or is the first note a late (odd) step of a swung line? Only on a clear
            # win: that freedom also lets a wrong tempo fit loose attacks.
            _, _, late_alignment, late_phase = grid_alignment(t, weights, periods, "late")
            j = int(np.argmax(late_alignment + rest))
            if late_alignment[j] + rest[j] > score[i] + .08:
                i, late = j, True
                swing_alignment, swing_phase = late_alignment, late_phase
        period = periods[i]
        # A swung grid also fixes which steps are the strong ones; without a clear win
        # (drums between the steps can tip it) that choice would be a coin toss.
        swung = late or swing_alignment[i] > align[i] + .03
        offset = swing_phase[i] if swung else phase[i]
        steps = STEPS * max(1, round(available / (STEPS * period)))
        exact_period = available / steps
        if abs(available - period * steps) < .021 and periods.min() <= exact_period <= periods.max():
            period = exact_period
        bpm = 60 / (subdiv * period)
    else:
        period = 60 / (bpm * subdiv)
        align, phase, swing_alignment, swing_phase = grid_alignment(t, weights, np.array([period]), mode)
        if free:
            fixed = grid_alignment(t, weights, np.array([period]), "fixed")
            if max(align[0], swing_alignment[0]) - max(fixed[0][0], fixed[2][0]) <= MOVE_FROM_FIRST_SOUND:
                free, anchored, start, mode = False, True, heard, "fixed"
                align, phase, swing_alignment, swing_phase = fixed
        swung = swing_alignment[0] > align[0] + .03
        offset = swing_phase[0] if swung else phase[0]
        if anchored:
            _, _, late_alignment, late_phase = grid_alignment(t, weights, np.array([period]), "late")
            if late_alignment[0] > max(align[0], swing_alignment[0]) + .08:
                swung, offset = True, late_phase[0]
    period = 60 / (bpm * subdiv)
    if free:
        # Fine-tune the phase on the attacks that sit on the (even) grid lines, then put
        # step 1 on the first full step: the audio may begin inside a step.
        every = 2 if swung else 1
        cycles = t / period - offset
        near = np.abs(cycles / every - np.rint(cycles / every)) * every < .2
        if np.sum(near) >= 3:
            deviation = cycles[near] - every * np.rint(cycles[near] / every)
            # The attacks of a played line wander a few ms around the steps, and the hold
            # of a note is read at the end of its step: a grid on the median attack lets
            # the early attacks into the hold of the notes before them (false slides).
            # So the steps start a little ahead of the early attacks.
            middle = np.median(deviation)
            ahead = 2.5 * np.median(np.abs(deviation - middle)) + .003 / period
            offset += middle - min(ahead, .15, .015 / period)
        lines = origin + .003 + (offset + every * np.arange(-2, 6)) * period
        first = lines[lines >= heard - .012][0]
        start = heard if abs(first - heard) < .012 else float(first)
        available = len(audio) / SR - start
        onsets = onsets + origin - start
    elif anchored and swung and offset > .5:
        # The first note is a late (odd) step of a swung line: step 1 is the next one.
        start = heard + offset * period
        available = len(audio) / SR - start
        onsets = onsets + origin - start
    if STEPS * period > available + .025:
        raise ValueError("the audio ends before the 16 steps do.")
    if shuffle is None:
        phase = (onsets - .003) / period
        nearest = np.floor(phase + .12).astype(int)
        err = phase - nearest
        offsets = [err[(nearest % 2 == parity) & (err >= -.12) & (err <= .68)] for parity in (0, 1)]
        shuffle = 0.
        if all(len(values) >= 4 for values in offsets):
            even, odd = map(np.median, offsets)
            if .045 < odd - even <= .66 and np.median(np.abs(offsets[1] - odd)) < .065:
                shuffle = float(odd - even)
    return Grid(float(bpm), float(start), subdiv, float(shuffle))


def matching_positions(audio, grid):
    """Start of every loop that repeats the first one."""
    first = round(grid.start * SR)
    length = round(grid.duration * SR)
    position = [first]
    low = signal.sosfiltfilt(signal.butter(3, 240, fs=SR, output="sos"), audio)
    features = np.array([envelope(low, .020)[::64], envelope(audio, .010)[::64]])
    indices = (first + np.arange(0, length, 64)) // 64
    indices = np.clip(indices, 0, features.shape[1] - 1)
    model = features[:, indices]
    for j in range(1, 12):
        start = round((grid.start + j * grid.duration) * SR)
        if start + length > len(audio) + round(.009 * SR):
            break
        current = features[:, np.clip((start + np.arange(0, length, 64)) // 64, 0, features.shape[1] - 1)]
        corr = np.corrcoef(model.ravel(), current.ravel())[0, 1]
        if corr > .69:
            position.append(start)
    return position


def subtract_kick(audio, grid, lock_bpm):
    """Take out the kick: the waveform shared by the beats that match it closely."""
    beat = 60 / grid.bpm * SR
    start = (grid.start * SR) % beat
    expected = start + np.arange(max(0, int((len(audio) - start) / beat) + 1)) * beat
    if len(expected) < 5:
        return audio, grid, 0
    bass = signal.sosfiltfilt(signal.butter(3, [35, 210], fs=SR, btype="bandpass", output="sos"), audio)
    radius, width = round(.019 * SR), round(.076 * SR)
    padded = np.pad(bass, (radius, radius + width))
    required = max(5, len(expected) * .65)

    def align(reference):
        beats, aligned = [], []
        ref_norm = np.linalg.norm(reference)
        if len(reference) != width or ref_norm < 1e-8:
            return beats, aligned
        for i, prediction in enumerate(expected):
            rough = round(prediction)
            window = padded[rough:rough + width + 2 * radius]
            corr = signal.correlate(window, reference, mode="valid")
            energy = signal.convolve(window ** 2, np.ones(width), mode="valid")
            corr /= np.maximum(ref_norm * np.sqrt(np.maximum(0, energy)), 1e-10)
            peak = int(np.argmax(corr))
            if not 0 < peak < len(corr) - 1 or corr[peak] < .89:
                continue
            a, b, c = corr[peak - 1:peak + 2]
            fraction = .5 * (a - c) / (a - 2 * b + c)
            position = rough + peak - radius + fraction
            if position >= -.001 * SR:
                beats.append(i)
                aligned.append(max(0., position))
        return beats, aligned

    beats, aligned = align(bass[round(start):round(start) + width])
    if len(aligned) < required:
        # A loud note on the first beat can spoil this reference: use the median beat.
        onsets = np.rint(expected).astype(int)
        onsets = onsets[onsets + width <= len(bass)]
        if len(onsets) >= required:
            reference = np.median(bass[onsets[:, None] + np.arange(width)], axis=0)
            beats, aligned = align(reference)
    if len(aligned) < required:
        return audio, grid, 0
    fit = np.polyfit(beats, aligned, 1)
    jitter = np.abs(np.polyval(fit, beats) - aligned)
    if np.median(jitter) > .002 * SR:
        return audio, grid, 0

    length = round(min(beat, fit[0]))
    offsets = np.arange(length)
    indices = np.arange(len(audio))
    complete = [p for p in aligned if p + length <= len(audio)]
    if len(complete) < 4:
        return audio, grid, 0
    kick = np.median([np.interp(p + offsets, indices, audio) for p in complete], axis=0)
    fade = min(round(.001 * SR), length // 2)
    kick[-fade:] *= np.linspace(1., 0., fade)
    result = audio.copy()
    for position in aligned:
        j = round(position)
        stop = min(j + length, len(audio))
        result[j:stop] -= np.interp(indices[j:stop] - position, offsets, kick)
    bpm = 60 * SR / fit[0]
    if not lock_bpm and abs(grid.bpm - bpm) < 1 and 60 <= bpm <= 200:
        grid = Grid(float(bpm), grid.start, grid.subdiv, grid.shuffle)
    return result, grid, len(aligned)


def remove_transients(audio):
    """Mask the short, broadband peaks (drum hits) and let the harmonics through."""
    width, hop = 4096, 192
    _, _, spectrum = signal.stft(audio, SR, nperseg=width, noverlap=width - hop)
    mag = np.abs(spectrum)
    horizontal = ndimage.median_filter(mag, size=(1, 15))
    vertical = ndimage.median_filter(mag, size=(19, 1))
    mask = horizontal ** 2 / (horizontal ** 2 + (1.2 * vertical) ** 2 + 1e-20)
    _, partial = signal.istft(spectrum * mask, SR, nperseg=width, noverlap=width - hop)
    return partial[:len(audio)]


def drums_likely(audio):
    """True when drum hits (hi-hats, snares, claps) seem to play along: most of the sound
    above 5 kHz comes in short broadband bursts. A line alone keeps its high harmonics
    between its attacks."""
    high = signal.sosfiltfilt(signal.butter(4, 5000, "hp", fs=SR, output="sos"), audio)
    energy = np.sum(high ** 2)
    if energy < 2e-4 * np.sum(audio ** 2):
        return False
    return np.sum(remove_transients(high) ** 2) < .45 * energy


def yin(audio, center, rate):
    width = 430
    max_lag = round(rate / 29)
    sample = np.arange(center - (width + max_lag) // 2, center + (width + max_lag) // 2 + 1)
    a = audio[np.clip(sample, 0, len(audio) - 1)].copy()
    a -= a.mean()
    power = np.r_[0., np.cumsum(a ** 2)]
    r = signal.correlate(a, a[:width], method="fft")[width - 1:width - 1 + max_lag]
    d = power[width] + power[width:width + max_lag] - power[:max_lag] - 2 * r
    d = np.maximum(d, 0.)
    y = d * np.arange(max_lag) / (np.cumsum(d) + 1e-12)
    y[0] = 1
    peaks = signal.find_peaks(-y)[0]
    peaks = peaks[(peaks >= round(rate / 1050)) & (peaks < max_lag - 1)]
    if not len(peaks):
        return np.nan, 0.
    valid = peaks[y[peaks] < .22]
    j = int(valid[0] if len(valid) else peaks[np.argmin(y[peaks])])
    delta = .5 * (y[j - 1] - y[j + 1]) / (y[j - 1] - 2 * y[j] + y[j + 1] + 1e-12)
    return 69 + 12 * np.log2(rate / ((j + delta) * 440)), float(max(0., 1 - y[j]))


NEUTRAL = (.40, .50, .50, .50, .50, 0., .80)   # knobs for listening to candidate notes
PHASES = np.arange(6) / 6


def play(rt, grid, tuning, notes, slides, accents, values, waveform, frames, phase=0.):
    """The studio's real-time engine playing the pattern from its first step."""
    params = np.zeros(rt.NPARAMS)
    for key, val in zip(FIT_KEYS, values):
        params[rt.RealtimeEngine._PIDX[key]] = val
    for index, val in ((rt.P_WAVE, waveform == "square"), (rt.P_BPM, grid.bpm),
                       (rt.P_TUNING, tuning), (rt.P_GATE, .55),
                       (rt.P_SUBDIV, grid.subdiv), (rt.P_SWING, grid.shuffle),
                       (rt.P_PLAY, 1.)):
        params[index] = val
    frequency = np.where(notes >= 0, 440 * 2. ** ((notes - 69) / 12), -1.)
    output = np.empty(frames)
    state = np.zeros(rt.NSTATE)
    state[rt.S_PHASE] = phase                   # where the oscillator starts in its cycle
    rt.synth_block(output, frames, state, params, frequency,
                   np.asarray(accents, dtype=float), np.asarray(slides, dtype=float), STEPS, float(SR))
    return output


def settle_glides(audio, reduced, grid, positions, notes, slides, tuning, rt):
    """Target note of every slid step, found by letting the engine play the candidates.

    At usual tempos a glide is still on its way when the step ends, and the pitch
    reader (a window of ~40 ms) lags behind it, so a big slide reads short of its
    target. Each candidate note is played by the studio's engine with the notes
    around it and read the same way as the audio; the closest one is kept."""
    rate = SR / 4
    lengths = np.diff(grid.edges)
    portions = np.linspace(.25, .90, 9)
    level = envelope(audio, .010)
    for j in [*range(1, STEPS), 0]:
        if not (slides[j - 1] and notes[j] >= 0 and notes[j - 1] >= 0):
            continue
        loops = positions
        if j == 0:
            # Step 1 only glides when step 16 of the loop before is in the audio.
            before = round(lengths[-1] * SR)
            loops = [p for p in positions if p >= before
                     and np.median(level[p - before:p]) > .3 * np.median(level[p:p + before])]
        if not loops:
            continue
        times = grid.edges[j] + portions * lengths[j]
        read = np.array([[yin(reduced, round((p / SR + t) * rate), rate) for t in times]
                         for p in loops])
        midi, confidence = np.median(read[..., 0], axis=0), np.median(read[..., 1], axis=0)
        usable = np.isfinite(midi) & (confidence > .5)
        if usable.sum() < 4:
            continue
        frames = round((grid.duration + grid.edges[j + 1]) * SR)
        mismatch = {}
        for candidate in range(max(12, notes[j] - 3), min(108, notes[j] + 3) + 1):
            trial = notes.copy()
            trial[j] = candidate
            # A fast glide reads differently with where the waveform's cycles fall, so
            # the engine plays it from several phases, as the loops of the audio do.
            heard = []
            for phase in PHASES:
                played = signal.resample_poly(play(rt, grid, tuning, trial, slides, np.zeros(STEPS),
                                                   NEUTRAL, "saw", frames, phase), 1, 4)
                heard.append([yin(played, round((grid.duration + t) * rate), rate)[0] for t in times])
            heard = np.median(heard, axis=0)
            ok = usable & np.isfinite(heard)
            mismatch[candidate] = (np.average((midi[ok] - heard[ok]) ** 2, weights=confidence[ok])
                                   if ok.sum() >= 4 else np.inf)
        best = min(mismatch, key=mismatch.get)
        # Change a note only for a clearly better match (half the mismatch, and close).
        if (best != notes[j] and mismatch[best] < .5 * mismatch.get(notes[j], np.inf)
                and mismatch[best] < .35 ** 2):
            notes[j] = best


def transcribe(audio, grid, positions, rt, tuning=None, mix=False):
    starts = grid.edges[:-1][None, :] * SR + np.array(positions)[:, None]
    lengths = np.diff(grid.edges) * SR
    sample_rate = SR / 4
    reduced = signal.resample_poly(audio, 1, 4)
    amp = envelope(audio, .009)
    fractions = np.array([.22, .31, .40, .49, .58, .67, .76, .90, .95, .98])
    ids = np.round(starts[..., None] + lengths[None, :, None] * fractions).astype(int)
    ids = np.clip(ids, 0, len(audio) - 1)
    amp_steps = np.median(amp[ids], axis=0)
    core = np.median(amp_steps[:, 1:5], axis=1)
    active = core >= .085 * np.max(core)
    tail = np.median(amp_steps[:, -3:], axis=1) / np.maximum(core, 1e-12)
    slides = active & np.roll(active, -1) & (tail > .54)
    measurements = np.array([yin(reduced, int(round(i / 4)), sample_rate)
                             for i in ids[..., :7].flat]).reshape((*ids[..., :7].shape, 2))
    midi = measurements[..., 0]
    conf = measurements[..., 1] ** 2 * np.array([.60, .90, 1., 1., .95, .80, .50])
    # The target pitch of a slid note is read towards the end of the glide.
    conf[:, np.roll(slides, 1), :] *= np.array([.10, .18, .40, .75, 1., 1.15, 1.])
    conf *= amp[ids[..., :7]] > .32 * core[None, :, None]
    conf *= active[None, :, None]
    conf[~np.isfinite(midi)] = 0
    midi = np.nan_to_num(midi)
    if tuning is None:
        stable = conf >= .52
        if np.any(stable):
            phase = np.sum(conf[stable] * np.exp(2j * np.pi * midi[stable]))
            tuning = float(440 * 2 ** (np.angle(phase) / (24 * np.pi)))
        else:
            tuning = 440.
    offset = 12 * np.log2(tuning / 440)
    quantised = np.rint(midi - offset).astype(int)
    notes = np.full(STEPS, -1)
    uncertainty = []
    for j in np.flatnonzero(active):
        votes = np.bincount(np.clip(quantised[:, j].ravel(), 0, 127),
                            weights=conf[:, j].ravel(), minlength=128)
        note = int(np.argmax(votes))
        if votes[note] <= 0:
            uncertainty.append(j + 1)
            continue
        if votes[note] < .57 * votes.sum():
            uncertainty.append(j + 1)
        notes[j] = note
    if not mix and np.any(active & (notes < 0)):
        raise ValueError("the pitch of some audible steps cannot be found; try an isolated "
                         "bass line, or --mix if drums play along.")
    if not np.any(notes >= 0):
        raise ValueError("no periodic note found.")
    settle_glides(audio, reduced, grid, positions, notes, slides, tuning, rt)
    return notes, slides, active, core, amp_steps, float(tuning), uncertainty


def refine_tuning(audio, grid, positions, notes, slides, tuning):
    """Measure the frequency where the notes are the most periodic."""
    reduced = signal.resample_poly(audio, 1, 4)
    rate = SR / 4
    measures = []
    for start in positions:
        for j in np.flatnonzero((notes >= 0) & ~np.roll(slides, 1)):
            for part in (.36, .52):
                center = (start / SR + grid.edges[j] + part * np.diff(grid.edges)[j]) * rate
                midi, confidence = yin(reduced, round(center), rate)
                hz = 440 * 2 ** ((midi - notes[j]) / 12)
                if confidence > .78 and abs(hz - tuning) < 6:
                    measures.append((hz, confidence))
    if len(measures) >= 6:
        measures = np.array(measures)
        limit = np.quantile(measures[:, 1], .78)
        tuning = np.median(measures[measures[:, 1] >= limit, 0])
    return float(np.clip(tuning, 400, 480))


def initial_accents(notes, active, slides, core, amp):
    """First guess of the accents, from how long a note holds after its gate."""
    released = active & ~slides
    accents = np.zeros(STEPS, dtype=bool)
    if np.sum(released) >= 4:
        sustain = amp[:, 6] / np.maximum(core, 1e-12)
        typical = np.median(sustain[released])
        for j in np.flatnonzero(released):
            peers = released & (notes == notes[j])
            reference = np.median(sustain[peers]) if np.sum(peers) >= 3 else typical
            accents[j] = sustain[j] > max(1.14 * reference, reference + .012)
    gain = core / max(np.median(core[active]), 1e-12)
    accents |= active & (gain > 1.38)
    return accents


def load_engine(folder):
    if folder is not None:
        folder = folder.resolve()
        if (folder / "Python_Scripts").is_dir():
            folder = folder / "Python_Scripts"
    else:
        folder = Path(__file__).resolve().parent
    if not (folder / "tb303_rt.py").is_file():
        raise ValueError("put this script in Python_Scripts, or give the studio folder with --studio.")
    sys.path.insert(0, str(folder))
    try:
        import numba  # noqa: F401
    except ImportError as exc:
        raise ValueError("Numba is needed for the fitting: python -m pip install numba") from exc
    import tb303_rt
    if not tb303_rt._HAS_NUMBA:
        raise ValueError("the studio's engine cannot load Numba.")
    return tb303_rt


class SoundFit:
    def __init__(self, audio, grid, positions, notes, slides, tuning, rt, peak=1.0):
        self.rt = rt
        self.grid = grid
        self.tuning = tuning
        self.notes = notes
        self.period = round(grid.duration * SR)
        self.frames = self.period * (2 if slides[-1] else 1)
        self.slides = slides
        times = grid.edges[:-1, None] + np.diff(grid.edges)[:, None] * np.array([.13, .27, .42, .56, .68, .80, .92])
        self.indices = np.rint(times * SR).astype(int)[..., None] + np.arange(-1152, 1152)
        window = signal.windows.hann(self.indices.shape[-1])
        self.window = window / np.linalg.norm(window)
        self.nfft = 4096
        edges = [0, 43, 85, 107, 128, 171, 214, 257, 300, 344, 387, 430, 473, 517,
                 580, 660, 740, 850, 1000, 1250, 1600, 2200, 3000, 4500, 6500, 10000, 16000]
        self.bins = np.rint(np.array(edges) * self.nfft / SR).astype(int)
        self.band_weights = np.array([.4, .9, 1., 1., 1., 1., 1., 1., 1., 1.2, 1.2, 1.2,
                                      1.15, 1., .9, .9, .9, .85, .85, .8, .75, .65, .65,
                                      .55, .5, .45, .35])
        features = [self.features(audio, start) for start in positions]
        levels = np.median([f[0] for f in features], axis=0)
        bands = np.median([f[1] for f in features], axis=0)
        self.target_spectrum, self.target_envelope = self.decibels(levels, bands)
        # Loudness of the audio itself (before it was scaled to a peak of 1), in dBFS.
        rms = np.median([np.sqrt(np.mean(audio[p:p + self.period] ** 2)) for p in positions])
        self.target_level = 20 * np.log10(max(rms * peak, 1e-9))

    def features(self, audio, start=0):
        indices = self.indices + start
        valid = (indices >= start) & (indices < min(start + self.period, len(audio)))
        frame = audio[np.clip(indices, 0, len(audio) - 1)] * self.window * valid
        levels = np.linalg.norm(frame, axis=-1)
        spectrum = np.abs(fft.rfft(frame, n=self.nfft, axis=-1)) ** 2
        bands = np.add.reduceat(spectrum, self.bins, axis=-1) * (2. / self.nfft)
        return levels, bands

    @staticmethod
    def decibels(levels, bands):
        maximum = max(np.max(levels), 1e-12)
        shape = 10 * np.log10(.000025 + bands / (levels[..., None] ** 2 + .015 * maximum ** 2))
        envelope_db = 20 * np.log10(.029 + levels / maximum)
        return shape, envelope_db

    def render(self, values, waveform, accents):
        return play(self.rt, self.grid, self.tuning, self.notes, self.slides, accents, values,
                    waveform, self.frames)

    def score(self, values, waveform, accents):
        output = self.render(values, waveform, accents)
        loop = output[self.frames - self.period:]
        spectrum, envelope_db = self.decibels(*self.features(output, self.frames - self.period))
        # Both waveforms get the same weight per frequency band; quiet moments
        # weigh less, so the noise between notes does not drive the fit.
        spectral = (spectrum - self.target_spectrum) ** 2 * self.band_weights
        weight = np.clip(10 ** (self.target_envelope / 20), .12, 1.)
        temporal = (envelope_db - self.target_envelope) ** 2
        level = 20 * np.log10(max(np.sqrt(np.mean(loop ** 2)), 1e-9))
        return float(np.sqrt(np.mean(spectral * weight[..., None]))
                     + .85 * np.sqrt(np.mean(temporal)) + .045 * accents.sum()
                     + LEVEL_WEIGHT * abs(level - self.target_level))

    def optimize(self, accents, iterations):
        candidates = []
        for waveform in ("saw", "square"):
            print(f"Fitting the sound with the {waveform} waveform...", flush=True)

            def objective(values):
                return self.score(values, waveform, accents)
            fit = optimize.differential_evolution(
                objective, FIT_BOUNDS, seed=303, maxiter=iterations, popsize=6,
                x0=[.25, .78, .40, .38, .60, .42, .86], tol=.009, polish=False,
            )
            candidates.append((fit.fun, fit.x, waveform))
        score, values, waveform = min(candidates, key=lambda candidate: candidate[0])
        print(f"Checking the accents ({waveform})...", flush=True)

        def polish(values, accents):
            baseline = self.score(values, waveform, accents)
            result = optimize.minimize(
                lambda p: self.score(p, waveform, accents), values, method="Powell",
                bounds=FIT_BOUNDS, options={"maxfev": 170, "ftol": .002, "xtol": .002},
            )
            return (result.fun, result.x) if result.fun < baseline else (baseline, values)

        # Try every accent and keep the changes that bring the render closer to the audio.
        def improve_accents(values, marks):
            score = self.score(values, waveform, marks)
            for j in np.flatnonzero(self.notes >= 0):
                marks[j] = ~marks[j]
                trial = self.score(values, waveform, marks)
                if trial < score - .04:
                    score = trial
                else:
                    marks[j] = ~marks[j]
            return score

        accents = accents.copy()
        score, values = polish(values, accents)
        if values[FIT_KEYS.index("accent")] < .4:
            # Way out of the minimum where misplaced accents push the ACCENT knob to zero.
            trials = []
            for strength in (.35, .65, .9):
                trial_values = values.copy()
                trial_values[FIT_KEYS.index("accent")] = strength
                marks = np.zeros(STEPS, dtype=bool)
                trial = improve_accents(trial_values, marks)
                if np.any(marks):
                    trials.append((trial, trial_values, marks))
            if trials:
                _, alternate, marks = min(trials, key=lambda trial: trial[0])
                improved, alternate = polish(alternate, marks)
                if improved < score:
                    score, values, accents = improved, alternate, marks
        for _ in range(2):
            if improve_accents(values, accents) >= score - .04:
                break
            score, values = polish(values, accents)
        return values, waveform, accents


def note_name(note):
    return NAME[note % 12] + str(note // 12 - 1)


def write_project(output, grid, scale, tuning, notes, slides, accents, values, waveform):
    knobs = dict(zip(FIT_KEYS, map(float, values)))
    knobs.update(bpm=grid.bpm, tuning=tuning, shuffle=grid.shuffle)
    settings = {
        "knobs": {key: round(val, 4) for key, val in knobs.items()},
        "waveform": waveform, "scale": scale, "playmode": "Forward",
    }
    pattern = [
        {"note": note_name(note) if note >= 0 else None, "accent": bool(accent), "slide": bool(slide)}
        for note, accent, slide in zip(notes, accents, slides)
    ]
    empty = [None] * (BANKS - 1)
    result = {
        "format": "tb303-studio", "version": 3, "patterns_saved": [1], **settings,
        "cur_bank": 0, "banks": [pattern, *empty], "bank_settings": [settings, *empty],
        "bank_instruments": [{"kind": "tb303", "name": "TB-303"}, *empty],
    }
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return pattern


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("audio", type=Path, help="a TB-303 line (WAV, MP3, FLAC, OGG...)")
    drums = parser.add_mutually_exclusive_group()
    drums.add_argument("--mix", action="store_true",
                       help="soften the drums of a mixed extract first (done anyway when hi-hats or snares are heard)")
    drums.add_argument("--no-mix", action="store_true", help="never soften drums, even when some are heard")
    parser.add_argument("-o", "--output", type=Path, help="the .tb303 project to write")
    parser.add_argument("--studio", type=Path, help="the TB303-Studio or Python_Scripts folder")
    parser.add_argument("--start", type=float, help="start of the loop in the audio, in seconds")
    parser.add_argument("--bpm", type=float, help="tempo to use, 60 to 200")
    parser.add_argument("--tuning", type=float, help="tuning to use, 400 to 480 Hz")
    parser.add_argument("--shuffle", type=float, help="shuffle to use, 0 to 0.66")
    parser.add_argument("--scale", choices=SCALES, default="1/16", help="step length (default 1/16)")
    parser.add_argument("--iterations", type=int, default=22, help="iterations per waveform (default 22)")
    args = parser.parse_args()
    ranges = {"start": (0, float("inf")), "bpm": (60, 200), "tuning": (400, 480),
              "shuffle": (0, .66), "iterations": (1, float("inf"))}
    for name, (low, high) in ranges.items():
        value = getattr(args, name)
        if value is not None and (not np.isfinite(value) or not low <= value <= high):
            parser.error(f"--{name} out of range")
    output = args.output or args.audio.with_name(args.audio.stem + "_from_audio.tb303")
    if output.suffix.lower() != ".tb303":
        parser.error("the output must end in .tb303")
    if args.audio.resolve() == output.resolve():
        parser.error("the input and the output must be different files")

    try:
        rt = load_engine(args.studio)
        print(f"Reading {args.audio.name}...", flush=True)
        audio, peak = read_audio(args.audio)
        print("Finding the tempo and the steps...", flush=True)
        grid = detect_grid(audio, SCALES[args.scale], args.start, args.bpm, args.shuffle)
        # Only the loops that are read matter (12 at most): a whole track would make the
        # drum softening slow and heavy.
        end = round((grid.start + 13 * grid.duration + 1) * SR)
        cut = round(grid.start * SR) - SR if grid.start > 10 else 0
        if cut or end < len(audio):
            audio = audio[cut:end]
            grid = Grid(grid.bpm, grid.start - cut / SR, grid.subdiv, grid.shuffle)
        start = round(grid.start * SR)
        mix = args.mix or (not args.no_mix and drums_likely(audio[start:start + 12 * SR]))
        if mix and not args.mix:
            print("Drums found: they are softened before the line is read.", flush=True)
        if mix:
            print("Taking the drums out...", flush=True)
            residual, grid, kicks = subtract_kick(audio, grid, args.bpm is not None)
            if kicks:
                print(f"Repeated kick taken out on {kicks} beats.", flush=True)
            print("Softening the other drum hits...", flush=True)
            audio = remove_transients(residual)
        positions = matching_positions(audio, grid)
        print("Reading the notes...", flush=True)
        notes, slides, active, core, amp, tuning, uncertain = transcribe(
            audio, grid, positions, rt, args.tuning, mix=mix)
        active = notes >= 0                  # with --mix, a step whose pitch is lost stays silent
        slides &= active & np.roll(active, -1)
        if args.tuning is None:
            tuning = refine_tuning(audio, grid, positions, notes, slides, tuning)
        print(f"{grid.bpm:.2f} BPM | tuning {tuning:.2f} Hz | shuffle {grid.shuffle:.3f} | "
              f"{len(positions)} loop(s) analysed", flush=True)
        if uncertain:
            print("Check the notes of steps " + ", ".join(map(str, uncertain)), flush=True)
        accents = initial_accents(notes, active, slides, core, amp)
        fitting = SoundFit(audio, grid, positions, notes, slides, tuning, rt, peak)
        values, waveform, accents = fitting.optimize(accents, args.iterations)
        pattern = write_project(output, grid, args.scale, tuning, notes, slides, accents, values, waveform)
    except (OSError, ValueError, ImportError) as error:
        parser.exit(1, f"Error: {error}\n")

    print("Pattern: " + " ".join((step["note"] or ".") + "+" * step["accent"] + "~" * step["slide"]
                                 for step in pattern), flush=True)
    print(f"Project written: {output}", flush=True)


if __name__ == "__main__":
    main()
