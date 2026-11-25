"""Pattern Play: the output clock owns bank changes. Tk only requests and observes them."""
from dataclasses import dataclass
from bisect import bisect_right
from types import SimpleNamespace
from typing import NamedTuple
import math, threading, time
import numpy as np
from classic_track import Bar
from classic_voice import render_engine
from clock24 import PulseTransport
from tb303 import TB303
from tb303_rt import RealtimeEngine
import instruments, instruments_rt

DIVISIONS={"1/8":2,"1/8T":3,"1/16":4,"1/16T":6,"1/32":8}

@dataclass
class Program:
    """Owned snapshot. It contains no Tk variables; it is safe to render on a worker."""
    slot: int
    sr: int
    settings: dict
    iid: str
    profile: str
    events: tuple
    sample: object = None
    transpose: int = 0

    def edges(self):
        k=self.settings["knobs"]
        return tuple(np.cumsum([self.sr*60./k["bpm"]/DIVISIONS[self.settings["scale"]]*
                                (1+k["shuffle"]*(-1)**i) for i in range(len(self.events))]))

    def ticks(self):
        k=self.settings["knobs"]
        return tuple(np.cumsum([24./DIVISIONS[self.settings["scale"]]*(1+k["shuffle"]*(-1)**i)
                                for i in range(len(self.events))]))

    def make_bar(self):
        if self.iid=="TB-303":
            e=RealtimeEngine(self.sr); e.set_profile(self.profile)
        else:
            e=instruments_rt.RealtimeSamplerEngine(self.sr)
            sample=(self.sample.s,self.sample.base) if self.sample is not None else instruments_rt.reference_sample(self.iid,self.sr)
            e.set_sample(*sample)
        for k,v in self.settings["knobs"].items(): e.set_param("swing" if k=="shuffle" else k,v)
        e.set_param("waveform",self.settings["waveform"]); e.set_param("subdiv",DIVISIONS[self.settings["scale"]])
        e.set_pattern(self.events)
        return Bar(e,(self.iid,self.profile),self.edges(),tuple(v["cell"] for v in self.events))

    def mixer_samples(self):
        """Retain the existing pygame voices (including the legacy offline synth)."""
        k=self.settings["knobs"]; div=DIVISIONS[self.settings["scale"]]
        params=dict(bpm=k["bpm"],tuning=k["tuning"],subdiv=div,swing=k["shuffle"],
                    play_mode="forward",cutoff=k["cutoff"],resonance=k["resonance"],
                    env_mod=k["env_mod"],decay=k["decay"],distortion=k["distortion"])
        if self.iid=="TB-303":
            if self.profile=="classic" or any(v.get("tie") for v in self.events):
                a=render_engine(self.make_bar().engine,1)
            else:
                a=TB303(self.sr).render(list(self.events),**params,waveform=self.settings["waveform"],accent=k["accent"])*k["volume"]/.9
        else:
            voice=self.sample.note if self.sample is not None else instruments.BUILTIN[self.iid]
            a=instruments.render_pattern(list(self.events),voice,**params,sr=self.sr)*k["volume"]
        # Some offline voices append a release tail. It must not lengthen a musical measure.
        frames=max(1,round(self.edges()[-1]))
        pcm=np.zeros((frames,2),np.int16); n=min(len(a),frames)
        data=np.asarray(a[:n]); data=data[:,None] if data.ndim==1 else data
        pcm[:n]=(np.clip(data,-1.,1.)*32767).astype(np.int16)
        return pcm

def _location(spec):
    return spec.slot,getattr(spec,"transpose",0)

def _carry(old,new):
    return old.identity==new.identity and old.engine.state.shape==new.engine.state.shape

class PatternPlayer:
    """The fixed output device drives the current voice, even if the next bank is a sampler."""
    error=None
    def __init__(self,spec,clock=None):
        self.lock=threading.RLock()
        self.current=spec
        self.bar=spec.make_bar()
        self.bar.engine.set_playing(True)
        self.bar.engine.process(np.empty(0))    # compile on caller, never in the audio callback
        self.cycle=(); self.cycle_at=0; self.after_cycle=None
        self.beat_phase=0.; self.entry_pending=False
        self.serial=0
        self.target=None                       # (Program, Bar) installed together
        self.clock=clock
        self.pulse=_PatternPulse(self,clock) if clock is not None else None
        self._stops=clock.stops if clock is not None else 0

    def _cancel_on_stop(self):
        if self.clock is not None and self._stops!=self.clock.stops:
            self._stops=self.clock.stops
            self.target=None; self.cycle=(); self.after_cycle=None

    def snapshot(self):
        with self.lock:
            self._cancel_on_stop()
            return self.current,self.target[0] if self.target else None

    def request(self,spec):
        with self.lock:
            self._cancel_on_stop()
            self.serial+=1; ticket=self.serial
            self.cycle=(); self.after_cycle=None; self.target=None
            self._lookahead()
            if spec is None or _location(spec)==_location(self.current):return
            stops=self._stops
        # Cancel the former request BEFORE preparing a new voice. A slow first
        # sample load must never sneak an obsolete bank into the next measure.
        bar=spec.make_bar()
        bar.engine.process(np.empty(0))
        with self.lock:
            self._cancel_on_stop()
            if ticket!=self.serial or self._stops!=stops:return
            self.target=(spec,bar)
            if self.pulse:
                self.pulse.stage(spec,bar)
                if not self.clock.running or self.clock.tick<0:
                    self.pulse.activate_stopped()
            self._lookahead()

    def queue_playlist(self,specs,finish_series=False):
        # Prepare every engine on the UI thread, then publish the entire loop at once.
        with self.lock:
            single=len(specs)==1 and not (finish_series and self.cycle)
        if single:return self.request(specs[0])
        items=[]
        for spec in specs:
            b=spec.make_bar(); b.engine.process(np.empty(0)); items.append((spec,b))
        if not items:return self.request(None)
        with self.lock:
            self._cancel_on_stop(); self.serial+=1
            if finish_series and self.cycle and self.current.slot!=self.cycle[-1][0].slot:
                self.after_cycle=tuple(items); return
            supersedes=finish_series and bool(self.cycle)
            self.cycle=tuple(items);self.after_cycle=None
            self.cycle_at=int(not supersedes and _location(items[0][0])==_location(self.current))%len(items)
            self._stage_cycle()
            self._lookahead()

    def _stage_cycle(self):
        if self.after_cycle and self.cycle and self.current.slot==self.cycle[-1][0].slot:
            self.cycle,self.after_cycle,self.cycle_at=self.after_cycle,None,0
        if self.cycle:
            self.target=self.cycle[self.cycle_at]
            self.cycle_at=(self.cycle_at+1)%len(self.cycle)
            if len(self.cycle)==1:self.cycle=()
            if self.pulse:self.pulse.stage(*self.target)

    def _lookahead(self):
        b=self.bar
        n=self.target[1] if self.target else b
        b.engine.pat_f[b.engine.nsteps]=n.engine.pat_f[0] if _carry(b,n) else -1.

    def edit(self,spec):
        b=spec.make_bar(); b.engine.process(np.empty(0))
        with self.lock:
            if spec.slot!=self.current.slot: return
            old=self.bar; e=b.engine
            e.set_playing(True)
            if _carry(old,b):
                e.state[:]=old.engine.state; e.state[8]=min(e.state[8],e.nsteps-1)
            self.current,self.bar=spec,b
            if self.pulse: self.pulse.replace_current(spec,b)
            self._lookahead()

    def knob(self,slot,key,value):
        with self.lock:
            if slot!=self.current.slot: return
            self.current.settings["knobs"][key]=value
            self.bar.engine.set_param("swing" if key=="shuffle" else key,value)
            if key in ("bpm","shuffle"):
                self.bar.steps=self.current.edges()
                if self.pulse:self.pulse.ends[self.pulse.index]=self.current.ticks()

    def heard_cell(self):
        with self.lock:
            if self.pulse:return self.pulse.heard_cell()
            i=max(0,min(len(self.bar.cells)-1,int(self.bar.engine.state[8])))
            return self.bar.cells[i]

    def _remaining(self):
        # Use the oscillator's sequencer phase, not elapsed wall time. This remains
        # valid after a tempo or swing change and in reverse/random play order.
        b=self.bar; st=b.engine.state
        if st[13]<.5:return b.duration
        i=int(st[8]); prior=b.steps[i-1] if i else 0.
        return b.duration-prior-st[9]

    def _promote(self,over):
        old=self.bar; self.current,self.bar=self.target; self.target=None
        b=self.bar; e=b.engine
        e.set_playing(True)
        if _carry(old,b): e.state[:]=old.engine.state
        else: e.state[:]=0.
        # Let the native kernel enter event zero on its very next sample. Preserve
        # fractional phase and, on the same voice, the oscillator, filter, tie and slide.
        last=b.steps[-1]-(b.steps[-2] if len(b.steps)>1 else 0.)
        e.state[8]=e.nsteps-1; e.state[9]=last+over; e.state[13]=1.
        self.entry_pending=True
        self._stage_cycle(); self._lookahead()

    def _sound(self,out):
        self.bar.engine.process(out)
        self.beat_phase=(self.beat_phase+len(out)*self.current.settings["knobs"]["bpm"]/(60.*self.current.sr))%1.

    def fill(self,out,now=None):
        with self.lock:
            self._cancel_on_stop()
            if self.pulse:
                self.pulse.fill(out,now); return
            while len(out):
                if self.entry_pending:
                    # The first sample performs the kernel's real transition.
                    # Reading the old sentinel before it would imply a zero-length bar.
                    self._sound(out[:1]); out=out[1:]; self.entry_pending=False
                    continue
                if self.target is None:break
                left=self._remaining()
                n=max(0,math.ceil(left-1e-8))
                if n<=len(out):
                    if n:self._sound(out[:n])
                    self._promote(max(0.,n-left) if left>=-1. else 0.)
                    out=out[n:]
                    continue
                break
            if len(out):self._sound(out)

class _PatternPulse(PulseTransport):
    """Two reusable slots on the original 24-PPQN transport; never rewrite a track."""
    def __init__(self,owner,clock):
        self.owner=owner
        b=owner.bar
        routing=SimpleNamespace(after=lambda idx,_cmd:1-idx if owner.target else idx)
        super().__init__(SimpleNamespace(bars=[b,b],sr=owner.current.sr,track=routing),clock)

    def stage(self,spec,bar):
        i=1-self.index; self.score.bars[i]=bar; self.ends[i]=spec.ticks()

    def replace_current(self,spec,bar):
        self.score.bars[self.index]=bar; self.ends[self.index]=spec.ticks()
        self._engine=bar.engine; self.step=-1

    def _bar(self,index,continuity=True):
        if not continuity:index=self.index   # a new master START restarts the sounding bank
        old=self.index
        super()._bar(index,continuity)
        if index!=old:
            self.owner.current,self.owner.bar=self.owner.target
            self.owner.target=None
            self.owner._stage_cycle();self.owner._lookahead()

    def activate_stopped(self):
        index=1-self.index
        self._bar(index,True)
        self._engine.state[:]=0.
        self.start_tick=max(0,self.clock.tick+1)


class Clip(NamedTuple):
    spec: Program
    sound: object
    key: tuple
    levels: np.ndarray
    frames: int
    edges: tuple

class MixerPatterns:
    """SDL owns the join. Rendering a slow instrument must never stop the current loop."""
    clock=None
    def __init__(self,spec,pg,*,background=True):
        from collections import OrderedDict
        self.pg=pg; self.cv=threading.Condition(threading.RLock()); self.closed=False
        self.cycle=(); self.cycle_at=0; self.after_cycle=None
        self.cache=OrderedDict(); self.warm={}; self.target=self.edited=None
        self.error=self._warning=None; self.started=time.monotonic()
        self.active=self._clip(spec,spec.mixer_samples())
        self.known={id(self.active.sound):self.active}; self.queued=self.active
        self.channel=pg.mixer.find_channel(True)
        self.channel.play(self.active.sound); self.channel.queue(self.active.sound)
        self.started=time.monotonic()
        if background:
            threading.Thread(target=self._render_loop,daemon=True,name="303 render").start()
            threading.Thread(target=self._queue_loop,daemon=True,name="303 queue").start()

    @staticmethod
    def _key(spec):
        s=spec.settings
        return (_location(spec),spec.iid,id(spec.sample),spec.profile,s["waveform"],s["scale"],s["playmode"],
                tuple(sorted(s["knobs"].items())),
                tuple((e["cell"],e.get("note"),e.get("tie"),e.get("accent"),e.get("slide")) for e in spec.events))

    def _clip(self,spec,pcm):
        sound=self.pg.sndarray.make_sound(pcm)
        levels=np.maximum.reduceat(np.abs(pcm[:,0].astype(np.int32)),np.arange(0,len(pcm),512))/32768.
        return Clip(spec,sound,self._key(spec),levels,len(pcm),spec.edges())

    def _store(self,clip):
        key=clip.key; self.cache[key]=clip; self.cache.move_to_end(key)
        while len(self.cache)>8:self.cache.popitem(last=False)

    def _observe(self):
        sound=self.channel.get_sound()
        if sound is not None and sound is not self.active.sound:
            clip=self.known.get(id(sound))
            if clip is not None:
                old=self.active; self.active=clip; self.started=time.monotonic()
                self._store(old)
                if self.target and _location(self.target)==_location(clip.spec):
                    self.target=None
                    if self.after_cycle and self.cycle and clip.spec.slot==self.cycle[-1].slot:
                        self.cycle,self.after_cycle,self.cycle_at=self.after_cycle,None,0
                    if self.cycle:
                        self.target=self.cycle[self.cycle_at]
                        self.cycle_at=(self.cycle_at+1)%len(self.cycle)
                        if len(self.cycle)==1:self.cycle=()
                if self.edited and (self.edited.slot!=clip.spec.slot or self._key(self.edited)==clip.key):self.edited=None
        return sound

    def _service(self):
        if self.closed:return
        self._observe()
        wanted=self.target or self.edited
        nextclip=self.cache.get(self._key(wanted),self.active) if wanted else self.active
        if self.channel.get_queue() is not nextclip.sound:
            # SDL may have promoted the previous queue between our two reads.
            # Keep both objects alive until the promotion is observed.
            previous=self.queued
            self.known={id(c.sound):c for c in (self.active,previous,nextclip)}
            self.channel.queue(nextclip.sound)
            self.queued=nextclip
            self._observe()

    def snapshot(self):
        with self.cv:
            self._service()
            return self.active.spec,self.target

    def request(self,spec):
        with self.cv:
            self._service()
            self.cycle=();self.after_cycle=None
            self.target=spec if spec and _location(spec)!=_location(self.active.spec) else None
            self._service(); self.cv.notify_all()

    def edit(self,spec):
        with self.cv:
            self._service()
            if self.active.spec.slot!=spec.slot:return
            self.edited=spec; self._service(); self.cv.notify_all()

    def queue_playlist(self,specs,finish_series=False):
        with self.cv:
            self._service()
            if not specs or (len(specs)==1 and not (finish_series and self.cycle)):
                return self.request(specs[0] if specs else None)
            for s in specs:self.warm[self._key(s)]=s
            if finish_series and self.cycle and self.active.spec.slot!=self.cycle[-1].slot:
                self.after_cycle=tuple(specs);self.cv.notify_all();return
            i=int(not (finish_series and self.cycle) and _location(specs[0])==_location(self.active.spec))%len(specs)
            self.cycle=tuple(specs);self.after_cycle=None
            self.target=self.cycle[i]; self.cycle_at=(i+1)%len(self.cycle)
            if len(specs)==1:self.cycle=()
            self._service(); self.cv.notify_all()

    def prefetch(self,spec):
        with self.cv:
            self.warm[self._key(spec)]=spec; self.cv.notify_all()

    def _job(self):
        for s in (self.target,self.edited):
            if s and self._key(s) not in self.cache and self._key(s)!=self.active.key:return s
        while self.warm:
            spec=self.warm.pop(next(iter(self.warm)))
            if self._key(spec) not in self.cache and self._key(spec)!=self.active.key:return spec

    def render_one(self,wait=False):
        with self.cv:
            job=None if self.closed else self._job()
            while not self.closed and job is None and wait:
                self.cv.wait(); job=self._job() if not self.closed else None
            if self.closed or job is None:return False
        try:
            pcm=job.mixer_samples()              # no SDL or Tk state while rendering DSP
        except Exception as exc:
            with self.cv:
                # A bad or stale prefetch must never silence the playing bank.
                if self.target is job or self.edited is job:
                    self._warning=str(exc)
                if self.target is job:self.target=None
                if self.edited is job:self.edited=None
                self._service()
            return True
        with self.cv:
            if not self.closed:
                self._store(self._clip(job,pcm)); self._service()
        return True

    def take_warning(self):
        with self.cv:
            msg,self._warning=self._warning,None
            return msg

    def _render_loop(self):
        try:
            while self.render_one(wait=True):pass
        except Exception as exc:self.error=str(exc)

    def _queue_loop(self):
        try:
            with self.cv:
                while not self.closed:
                    self._service(); self.cv.wait(.003)
        except Exception as exc:self.error=str(exc)

    def _position(self):
        return int(max(0.,time.monotonic()-self.started)*self.active.spec.sr)%self.active.frames

    def heard_cell(self):
        with self.cv:
            self._service()
            i=min(len(self.active.edges)-1,bisect_right(self.active.edges,self._position()))
            return self.active.spec.events[i]["cell"]

    def get_level(self):
        with self.cv:return float(self.active.levels[self._position()//512])

    def finish(self):
        with self.cv:
            self._observe(); self.closed=True
            self.channel.stop(); self.target=self.edited=None
            self.cv.notify_all()
            return self.active.spec
