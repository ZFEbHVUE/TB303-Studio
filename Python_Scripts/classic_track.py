"""Sample-clock transport. Same bar plan and voice kernels for playback and export."""
from bisect import bisect_right
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import math, os, threading, time, wave
import numpy as np
from classic_sequence import Track, transposed


@dataclass
class Bar:
    engine: object
    identity: tuple
    # Real-valued lengths; avoid one-rounding-per-step or per-bar drift.
    steps: tuple
    cells: tuple

    @property
    def duration(self):
        return self.steps[-1]


class Score:
    def __init__(self, track, make_bar, sr):
        self.track=Track.read(track.dump())
        if not self.track.bars:
            raise ValueError("The track is empty.")
        self.sr=sr
        cache={}
        self.bars=[]
        for pair in self.track.bars[:self.track.end+1]:
            if pair not in cache:
                cache[pair]=make_bar(*pair)
            self.bars.append(cache[pair])

    @property
    def frames(self):
        return math.ceil(sum(b.duration for b in self.bars)-1e-8)


class Transport:
    def __init__(self, score, start_at=0):
        self.score=score
        self.index=0
        self.pos=0; self.beat_phase=0.
        self.overhang=0.
        self.pending=None
        self.rounds=0
        self.engine=None
        self._enter(max(0,min(len(score.bars)-1,int(start_at))))

    def _enter(self, index):
        old=self.engine
        prev=self.score.bars[self.index].identity
        self.index=index
        b=self.score.bars[index]
        self.engine=e=b.engine
        carry=old.state.copy() if old is not None and prev==b.identity else None
        e.set_playing(True)
        if carry is None:
            e.state[:]=0.
        else:
            e.state[:]=carry
        e.state[8]=0.; e.state[9]=self.overhang; e.state[13]=0.
        self.pos=0
        self.limit=max(1,math.ceil(b.duration-self.overhang-1e-8))
        self._lookahead()

    def _lookahead(self):
        b=self.score.bars[self.index]
        ni=self.score.track.after(self.index,self.pending)
        nextbar=self.score.bars[ni]
        self.engine.pat_f[self.engine.nsteps]=(nextbar.engine.pat_f[0]
                         if b.identity==nextbar.identity else -1.)

    def request(self, which):
        if which not in ("ds","reset"):
            raise ValueError("Unknown transport command.")
        self.pending=which

    def heard_cell(self):
        bar=self.score.bars[self.index]
        i=min(len(bar.cells)-1,bisect_right(bar.steps,self.pos+self.overhang))
        return bar.cells[i]

    def fill(self, dest):
        off=0
        while off<len(dest):
            self._lookahead()
            n=min(len(dest)-off,self.limit-self.pos)
            self.engine.process(dest[off:off+n])
            self.beat_phase=(self.beat_phase+n*self.engine.params[5]/(60.*self.score.sr))%1.
            self.pos+=n; off+=n
            if self.pos>=self.limit:
                self.overhang+=self.limit-self.score.bars[self.index].duration
                nxt=self.score.track.after(self.index,self.pending)
                self.pending=None
                if nxt==0:
                    self.rounds+=1
                self._enter(nxt)


def export_score(score,path):
    """Stream one pass through D.C.; never allocate an entire song as float PCM."""
    player=Transport(score)
    tmp=Path(str(path)+".part")
    try:
        with wave.open(str(tmp),"wb") as out:
            out.setparams((2,2,score.sr,0,"NONE","not compressed"))
            left=score.frames
            while left:
                buf=np.empty(min(left,4096))
                player.fill(buf)
                pcm=(np.clip(buf,-1,1)*32767.).astype("<i2")
                out.writeframesraw(np.repeat(pcm,2).tobytes())
                left-=len(buf)
        os.replace(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)


class MixerTrack:
    """Fallback for pygame: prepare each measure; queue boundaries in SDL, not Tk.
    A D.S. command replaces the already queued next measure on the same channel.
    """
    def __init__(self, score, pygame, start_at=0):
        self.score,self.pg=score,pygame
        self.halt=threading.Event()
        self.lock=threading.Lock()
        self.index=max(0,min(len(score.bars)-1,int(start_at))); self.started=None; self.progress=0
        self.pending=None; self.error=None; self.channel=None
        self.sounds=[]; self.levels=[]
        self.thread=threading.Thread(target=self._work,daemon=True)
        self.thread.start()

    def _work(self):
        try:
            p=Transport(self.score)
            for i in range(len(self.score.bars)):
                if self.halt.is_set(): return
                buf=np.empty(p.limit); off=0
                while off<len(buf):
                    if self.halt.is_set(): return
                    n=min(2048,len(buf)-off)
                    p.fill(buf[off:off+n]); off+=n
                pcm=(np.clip(buf,-1,1)*32767).astype(np.int16)
                self.sounds.append(self.pg.sndarray.make_sound(np.repeat(pcm[:,None],2,axis=1)))
                self.levels.append(np.maximum.reduceat(np.abs(buf),np.arange(0,len(buf),512)))
                self.progress=i+1
            with self.lock:
                if self.halt.is_set(): return
                self.channel=self.pg.mixer.find_channel(True)
                self.channel.play(self.sounds[self.index])
                self.started=time.monotonic()
                queued=self.score.track.after(self.index,self.pending)
                self.channel.queue(self.sounds[queued])
            # SDL promotes the queued buffer at the precise sample boundary.
            while not self.halt.wait(.003):
                with self.lock:
                    if self.channel.get_queue() is None:
                        self.index=queued; self.pending=None
                        self.started=time.monotonic()
                        if not self.channel.get_busy():
                            self.channel.play(self.sounds[queued])
                    desired=self.score.track.after(self.index,self.pending)
                    if self.channel.get_queue() is None or desired!=queued:
                        queued=desired
                        self.channel.queue(self.sounds[queued])
        except Exception as exc:
            self.error=str(exc)

    def request(self,which):
        with self.lock: self.pending=which

    def position(self):
        if self.started is None: return 0
        return max(0,int((time.monotonic()-self.started)*self.score.sr))

    def heard_cell(self):
        b=self.score.bars[self.index]
        return b.cells[min(len(b.cells)-1,bisect_right(b.steps,self.position()))]

    def get_level(self):
        if self.started is None: return 0.
        values=self.levels[self.index]
        return float(values[min(len(values)-1,self.position()//512)])

    def stop(self):
        self.halt.set()
        with self.lock:
            if self.channel is not None:
                self.channel.stop()

