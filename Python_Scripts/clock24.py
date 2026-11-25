"""MIDI realtime clock input (24 ticks/quarter). Does not drive a physical DIN jack."""
from collections import deque
from bisect import bisect_right
import math, statistics, threading, time


class Clock24:
    def __init__(self):
        self.lock=threading.Lock(); self.running=False; self.tick=-1; self.last=None
        self.period=60./(24*120); self.generation=0; self.stops=0; self.intervals=deque(maxlen=9)

    def feed(self,kind,now=None):
        now=time.monotonic() if now is None else now
        with self.lock:
            if kind=="start":
                self.running=True; self.tick=-1; self.last=None; self.generation+=1
            elif kind=="stop": self.running=False; self.stops+=1
            elif kind=="continue":
                self.running=True; self.last=None
            elif kind=="clock":
                if self.last is not None:
                    dt=now-self.last
                    if .004<=dt<=.125:
                        self.intervals.append(dt); self.period=statistics.median(self.intervals)
                self.last=now
                if self.running: self.tick+=1

    def sample(self,now):
        with self.lock:
            if not self.running or self.tick<0 or self.last is None or now-self.last>max(.14,4*self.period):
                return self.generation,False,0.,self.period,0.
            return (self.generation,True,self.tick+max(0.,min(1.,(now-self.last)/self.period)),
                    self.period,self.tick+1.)


class PulseTransport:
    """Clock phase selects the event. No Tk timer advances notes or measures."""
    def __init__(self,score,clock):
        self.score,self.clock=score,clock
        self.ends=[tuple(v*b.engine.params[5]*24./(60.*score.sr) for v in b.steps) for b in score.bars]
        self.index=0; self.step=-1; self.start_tick=0.; self.epoch=None
        self.pending=None; self._engine=None; self.waiting=True

    def request(self,cmd): self.pending=cmd

    def _bar(self,index,continuity=True):
        prev=self._engine
        old=self.score.bars[self.index]
        bar=self.score.bars[index]; e=bar.engine
        carry=prev.state.copy() if continuity and prev is not None and old.identity==bar.identity else None
        e.set_playing(True)
        if carry is None: e.state[:]=0.
        else: e.state[:]=carry
        self._engine=e; self.index=index; self.step=-1

    def heard_cell(self):
        return self.score.bars[self.index].cells[max(0,self.step)]

    def fill(self,out,now=None):
        now=time.monotonic() if now is None else now
        epoch,running,tick,period,ceiling=self.clock.sample(now)
        self.waiting=not running
        if not running: out[:]=0.; return
        if epoch!=self.epoch:
            self.epoch=epoch; self.pending=None; self.start_tick=0.; self._bar(0,False)
        scale=period*self.score.sr; bpm=60./(24.*period)
        i=0
        while i<len(out):
            absolute=min(tick+i/scale,ceiling-1e-8)
            local=absolute-self.start_tick
            edges=self.ends[self.index]
            if local>=edges[-1]-1e-9:
                self.start_tick+=edges[-1]
                nxt=self.score.track.after(self.index,self.pending); self.pending=None
                self._bar(nxt); continue
            j=min(len(edges)-1,bisect_right(edges,local+1e-9))
            e=self._engine; e.set_param("bpm",bpm)
            nxt=self.score.track.after(self.index,self.pending)
            b,n=self.score.bars[self.index],self.score.bars[nxt]
            e.pat_f[e.nsteps]=(n.engine.pat_f[0] if n.identity==b.identity else -1.)
            origin=edges[j-1] if j else 0.
            age=max(0.,(local-origin)*scale)
            if j!=self.step:
                if j==0:
                    e.state[8]=0.; e.state[9]=age; e.state[13]=0.
                else:
                    before=edges[j-2] if j>1 else 0.
                    e.state[8]=j-1; e.state[9]=(origin-before)*scale+age+1e-6; e.state[13]=1.
                self.step=j
            else:
                e.state[8]=j; e.state[9]=age; e.state[13]=1.
            # If the next master tick is late, do not advance through it.
            if absolute>=ceiling-2e-8 and edges[j]+self.start_tick<=ceiling+1e-7:
                out[i:]=0.; return
            count=min(len(out)-i,max(1,math.ceil((edges[j]-local)*scale-1e-8)))
            e.process(out[i:i+count]); i+=count

