"""Capture stereo output blocks and write a live take outside the audio thread."""

import ctypes
import os
from pathlib import Path
import queue
import shutil
import sys
import tempfile
import threading
import wave

import numpy as np


class WaveTake:
    """Spool PCM to disk, then save the finished WAV where the player chooses."""

    def __init__(self, sample_rate):
        self.sample_rate = sample_rate
        self.recording = True
        self.frames = 0
        self.error = None
        self._lock = threading.Lock()
        self._blocks = queue.SimpleQueue()
        self._directory = tempfile.TemporaryDirectory(prefix="tb303-record-")
        self._path = Path(self._directory.name) / "take.wav"
        self._writer = threading.Thread(target=self._write, daemon=True)
        self._writer.start()

    def _submit(self, block):
        with self._lock:
            if self.recording and self.error is None:
                self._blocks.put(block)

    def capture_float(self, block):
        # PortAudio owns the buffer and will reuse it as soon as we return.
        self._submit(block.copy())

    def capture_pcm(self, block):
        self._submit(block)

    def add_silence(self, seconds):
        self._submit(round(seconds * self.sample_rate))

    def _write(self):
        try:
            with wave.open(str(self._path), "wb") as wav:
                wav.setparams((2, 2, self.sample_rate, 0, "NONE", "not compressed"))
                while (block := self._blocks.get()) is not None:
                    if isinstance(block, int):
                        pcm = bytes(block * 4)
                    elif isinstance(block, np.ndarray):
                        pcm = (np.clip(block, -1, 1) * 32767).astype("<i2").tobytes()
                    elif sys.byteorder == "big":
                        pcm = np.frombuffer(block, dtype=np.int16).astype("<i2").tobytes()
                    else:
                        pcm = block
                    if len(pcm) + self.frames * 4 > 0xFFFFFFFF - 36:
                        raise OSError("This recording reached the WAV file size limit.")
                    wav.writeframesraw(pcm)
                    self.frames += len(pcm) // 4
        except OSError as error:
            with self._lock:
                self.error = error

    def finish(self):
        with self._lock:
            if self.recording:
                self.recording = False
                self._blocks.put(None)
        self._writer.join()

    def save(self, path):
        # Leave any previous file alone if the write fails midway.
        destination = Path(path)
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as staging:
            temporary = Path(staging.name)
        try:
            shutil.copyfile(self._path, temporary)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)

    def close(self):
        self.finish()
        self._directory.cleanup()


class MixerOutputTap:
    """Listen to the SDL_mixer output already used by pygame."""

    _callback_type = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int)

    def __init__(self, mixer, sample_rate, on_audio):
        if mixer.get_init() != (sample_rate, -16, 2):
            raise RuntimeError("Recording needs a stereo, signed 16-bit pygame mixer at 44.1 kHz.")
        try:
            # Resolve SDL_mixer through pygame's loaded extension. A separately
            # loaded mixer library might have its own audio device and state.
            self._set_post_mix = ctypes.CDLL(mixer.__file__).Mix_SetPostMix
        except (AttributeError, OSError) as error:
            raise RuntimeError("This pygame build does not expose its SDL_mixer output.") from error
        self._set_post_mix.argtypes = (ctypes.c_void_p, ctypes.c_void_p)
        self._set_post_mix.restype = None

        @self._callback_type
        def receive(_userdata, stream, size):
            on_audio(ctypes.string_at(stream, size))

        self._receive = receive
        self._set_post_mix(self._receive, None)

    def close(self):
        self._set_post_mix(None, None)
