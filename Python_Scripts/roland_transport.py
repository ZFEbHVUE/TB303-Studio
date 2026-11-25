"""A read-only view of the clock already delivering sound. Never advance audio from Tk."""
from dataclasses import dataclass
from contextlib import nullcontext

@dataclass(frozen=True)
class TransportView:
    slot:int
    queued:object=None
    running:bool=False
    beat_on:bool=True
    bar:int=0
    shift:int=0
    cell:int=0

def read_transport(a,now,epoch=0.):
    live=a._live;track=a._track_player
    idle=(now-epoch)%0.5<.25
    if live is not None and hasattr(live,'audible_view'):return live.audible_view()
    if track is not None and hasattr(track,'audible_view'):return track.audible_view()
    if live is not None:
        guard=getattr(live,"lock",None) or getattr(live,"cv",None) or nullcontext()
        with guard:
            current,next_spec=live.snapshot()
            bpm=current.settings["knobs"]["bpm"]
            if live.clock is not None:
                _,on,ticks,_,_=live.clock.sample(now)
                beat=ticks%24<12 if on else idle
            elif hasattr(live,"bar"):
                beat=live.beat_phase<.5;on=True
            else:
                on=live.started is not None;phase=now-live.started if on else 0.
                beat=(phase*bpm/60.)%1.<.5 if on else idle
            return TransportView(current.slot,None if next_spec is None else next_spec.slot,
                    on,beat,a.bar_pos,getattr(current,"transpose",0),live.heard_cell())
    if track is not None:
        # The real-time host owns both the bar index and its sample offset.
        host=getattr(a,"_track_host",None)
        guard=getattr(host,"_lock",None) or getattr(track,"lock",None) or nullcontext()
        with guard:
            i=track.index;bar=track.score.bars[i];slot,shift=track.score.track.bars[i]
            if hasattr(track,"clock"):
                _,on,ticks,_,_=track.clock.sample(now);beat=ticks%24<12 if on else idle
            else:
                on=getattr(track,"started",True) is not None
                pos=track.pos if hasattr(track,"pos") else track.position()
                bpm=bar.engine.params[5]
                beat=getattr(track,'beat_phase',(pos*bpm/(60*track.score.sr))%1.)<.5 if on else idle
            return TransportView(slot,None,on,beat,i,shift,track.heard_cell())
    return TransportView(a.cur_bank,None,False,idle,a.bar_pos,getattr(a,"_panel_shift",0))
