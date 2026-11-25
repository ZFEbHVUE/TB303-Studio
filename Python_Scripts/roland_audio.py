"""Short SDL buffers for the photo panel's live knobs when PortAudio is unavailable."""
from dataclasses import dataclass
import math,threading,time
import numpy as np
from classic_track import MixerTrack,Transport
from live_pattern import PatternPlayer
from roland_transport import TransportView

def set_track_parameter(player,name,value):
    """Apply a performance control to this playing score, never to stored pattern pitches."""
    if name=="bpm" and hasattr(player,"clock"):return
    param="swing" if name=="shuffle" else name
    b=player.score.bars[player.index];before=b.steps;seen=set()
    oldpos=getattr(player,"pos",0)+getattr(player,"overhang",0)
    for bar in player.score.bars:
        if id(bar) in seen:continue
        seen.add(id(bar));e=bar.engine;e.set_param(param,value)
        if param in ("bpm","swing"):
            q=e._PIDX
            unit=player.score.sr*60./(e.params[q["bpm"]]*e.params[q["subdiv"]])
            swing=e.params[q["swing"]]
            bar.steps=tuple(np.cumsum([unit*(1+swing*(-1)**i) for i in range(len(bar.cells))]))
    if param not in ("bpm","swing"):return
    if hasattr(player,"clock"):
        player.ends=[tuple(x*b.engine.params[5]*24/(60.*player.score.sr) for x in b.steps) for b in player.score.bars]
    else:
        i=min(len(before)-1,int(np.searchsorted(before,oldpos,side="right")))
        prev=before[i-1] if i else 0.;newprev=b.steps[i-1] if i else 0.
        age=max(0.,min(1.,(oldpos-prev)/(before[i]-prev)))*(b.steps[i]-newprev)
        newpos=min(b.duration-1.,newprev+age)
        player.pos=int(newpos);player.overhang=newpos-player.pos
        player.limit=max(player.pos+1,math.ceil(b.duration-player.overhang-1e-8))
        # A native step-boundary sample can still be pending in the kernel.
        st=b.engine.state;ei=max(0,min(len(before)-1,int(st[8])))
        prior=before[ei-1] if ei else 0.;newprior=b.steps[ei-1] if ei else 0.
        st[9]*=(b.steps[ei]-newprior)/(before[ei]-prior)

@dataclass
class Block:
    sound:object
    rows:list
    level:float

class Output:
    chunk=512
    stride=64
    clock=None
    def __init__(self,player,sr,pg,background=True):
        self.player,self.sr,self.pg=player,sr,pg
        self.lock=threading.RLock();self.halt=threading.Event()
        self.error=None;self.channel=pg.mixer.find_channel(True)
        self.active=self.block();self.queued=self.block()
        self.channel.play(self.active.sound);self.started=time.monotonic()
        self.channel.queue(self.queued.sound)
        if background:threading.Thread(target=self.worker,daemon=True,name="303 photo output").start()

    def block(self):
        y=np.empty(self.chunk);rows=[]
        for i in range(0,len(y),self.stride):
            rows.append(self.capture());self.player.fill(y[i:i+self.stride])
        pcm=(np.clip(y,-1,1)*32767).astype(np.int16)
        return Block(self.pg.sndarray.make_sound(np.repeat(pcm[:,None],2,axis=1)),rows,float(np.max(np.abs(y))))

    def observe(self):
        s=self.channel.get_sound()
        if s is self.queued.sound and s is not self.active.sound:
            self.active=self.queued;self.started=time.monotonic()

    def service(self):
        with self.lock:
            if self.halt.is_set():return
            self.observe()
            if self.channel.get_queue() is None:
                if self.channel.get_sound() is None:
                    self.active=self.block();self.channel.play(self.active.sound);self.started=time.monotonic()
                self.queued=self.block();self.channel.queue(self.queued.sound)

    def worker(self):
        try:
            while not self.halt.wait(.002):self.service()
        except Exception as exc:self.error=str(exc)

    def row(self):
        self.observe()
        idx=max(0,min(len(self.active.rows)-1,int((time.monotonic()-self.started)*self.sr)//self.stride))
        return self.active.rows[idx]

    def stop(self):
        self.halt.set()
        with self.lock:self.channel.stop()
    def heard_cell(self):
        with self.lock:return self.row()[0].cell
    def get_level(self):
        with self.lock:self.observe();return self.active.level
    def audible_view(self):
        with self.lock:return self.row()[0]

class PatternOutput(Output):
    def __init__(self,spec,pg,background=True):
        super().__init__(PatternPlayer(spec),spec.sr,pg,background)
    def capture(self):
        p=self.player;s,n=p.snapshot()
        return TransportView(s.slot,None,True,p.beat_phase<.5,0,s.transpose,p.heard_cell()),s
    def snapshot(self):
        with self.lock:
            audible=self.row()[1];current,requested=self.player.snapshot()
            if requested is None and (audible.slot,audible.transpose)!=(current.slot,current.transpose):requested=current
            return audible,requested
    def audible_view(self):
        with self.lock:
            v=self.row()[0];_,n=self.snapshot()
            return TransportView(v.slot,n.slot if n else None,True,v.beat_on,0,v.shift,v.cell)
    def finish(self):
        with self.lock:
            s=self.row()[1];self.stop();return s
    def request(self,spec):self.player.request(spec)
    def queue_playlist(self,specs,finish_series=False):self.player.queue_playlist(specs,finish_series)
    def edit(self,spec):self.player.edit(spec)
    def knob(self,slot,key,value):self.player.knob(slot,key,value)

class TrackOutput(Output,MixerTrack):
    def __init__(self,score,pg,start_at=0,background=True):
        self.score=score;self.progress=len(score.bars)
        for bar in score.bars:bar.engine.process(np.empty(0))
        super().__init__(Transport(score,start_at),score.sr,pg,background)
    def capture(self):
        p=self.player;i=p.index;slot,shift=p.score.track.bars[i]
        return TransportView(slot,None,True,p.beat_phase<.5,i,shift,p.heard_cell()),None
    @property
    def index(self):
        with self.lock:return self.row()[0].bar
    def request(self,cmd):
        with self.lock:self.player.request(cmd)
    def knob(self,k,v):
        with self.lock:set_track_parameter(self.player,k,v)
