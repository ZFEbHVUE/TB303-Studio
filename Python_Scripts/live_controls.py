"""Glue between the Tk editor (selected/audible versus requested slot) and Pattern Play."""
from copy import deepcopy
from tkinter import messagebox
from live_pattern import PatternPlayer, MixerPatterns, Program

class LiveControls:
    def _program(self,slot,shift=None,inherit=True):
        if shift is None:
            shift=getattr(self,"_panel_shift",0)
            player=getattr(self,"_live",None)
            if player is not None:
                active,_=player.snapshot()
                if slot==active.slot:shift=getattr(active,"transpose",0)
        settings=self._capture_settings()
        saved=self.bank_settings[slot] if slot!=self.cur_bank else None
        if saved:
            settings["knobs"].update(saved.get("knobs",{}))
            for k in ("waveform","scale","playmode"):
                if k in saved: settings[k]=saved[k]
        unused=self.banks[slot] is None and self.patterns[slot] is None
        iid=self.instrument if slot==self.cur_bank or (inherit and unused) else self.bank_instr[slot]
        seq=self._ordered(slot,shift,settings["playmode"])
        return Program(slot,self.SR,deepcopy(settings),iid,self.profile,tuple(seq),
                       self.samples.get(iid,{}).get("sampler"),shift)

    def _playing_internal_pattern(self):
        return self.playing and self._live is not None and self._live.clock is None

    def _selector_slot(self):
        return self._pending_bank if self._pending_bank is not None else self.cur_bank

    def _start_live(self,clock=None):
        spec=self._program(self.cur_bank)
        host=self._active_engine()
        try:
            if host is not None and host.stream is not None and host.stream.active:
                player=PatternPlayer(spec,clock)
                with host._lock: host.track_source=player
            else:
                if clock is not None: raise RuntimeError("MIDI sync requires real-time audio output.")
                if not self._ensure_pygame():
                    raise RuntimeError(self.audio_err or "No audio output. You can still export a WAV file.")
                import pygame
                host=None
                photo=getattr(self,"_roland_view",None)
                if photo is not None and photo.visible:
                    from roland_audio import PatternOutput
                    player=PatternOutput(spec,pygame)
                else:player=MixerPatterns(spec,pygame)
            self._live_host=host; self._live=player; self._live_initial_iid=spec.iid
            self._pending_bank=None; self.playing=True
            self._vu_start(); self.refresh()
            if isinstance(player,MixerPatterns):
                start=8*(spec.slot//8)
                for slot in range(start,start+8):
                    if slot!=spec.slot and self.banks[slot] is not None:player.prefetch(self._program(slot))
        except Exception as exc:
            self._end_live(); self.playing=False; self._vu_stop()
            messagebox.showerror("Pattern Play",str(exc),parent=self.root)

    def _queue_live(self,slot):
        p=self._live
        self._poll_live()
        try:
            p.request(self._program(slot,shift=getattr(self,"_panel_shift",0)))
        except Exception as exc:
            messagebox.showerror("Pattern Play",str(exc),parent=self.root)
        self._poll_live()

    def cancel_live_request(self):
        if self._live:
            self._live.request(None); self._poll_live()

    def _poll_live(self):
        p=self._live
        if p is None:return
        current,target=p.snapshot()
        nxt=target.slot if target is not None else None
        changed=nxt!=self._pending_bank
        self._pending_bank=nxt
        if current.slot!=self.cur_bank:
            self._adopt_live(current)
        elif changed:self.refresh()
        if isinstance(p,MixerPatterns):
            warning=p.take_warning()
            if warning:
                self.last_action="Pattern not ready: "+warning
                self._face.say("PATTERN UNAVAILABLE")
                print(self.last_action)

    def _adopt_live(self,spec):
        # Only the view and the editor change here. The audio has already crossed
        # the boundary; don't stop a device, trigger the first note twice or lose a take.
        self._finish_gesture(); self._freeze_bank()
        self._enter_bank(spec.slot,live=spec)

    def _edit_live(self):
        p=self._live
        if p is None:return
        p.edit(self._program(self.cur_bank))
        _,pending=p.snapshot()
        if pending is not None and pending.profile!=self.profile:
            p.request(self._program(pending.slot))

    def _end_live(self):
        p=self._live
        if p is None:return False
        host=self._live_host
        if host is not None:
            with host._lock:
                host.track_source=None
                current,_=p.snapshot()
        else: current=p.finish()
        self._pending_bank=None
        if current.slot!=self.cur_bank:self._adopt_live(current)
        self._live=self._live_host=None
        return current.iid!=self._live_initial_iid

