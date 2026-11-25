"""Studio integration: undo boundaries, independent Pitch/Time lists and Track transport."""
from contextlib import contextmanager
from copy import deepcopy
from functools import wraps
from threading import Thread
import math, time
import tkinter as tk
from tkinter import ttk
import studio_messages as messagebox
import studio_file_dialog as filedialog
import numpy as np
from tb303 import apply_play_mode, DEMO_PATTERN
from classic_sequence import Pattern, Track, History, transposed, label, SLOTS, TRACKS, between
from classic_track import Score, Transport, MixerTrack, export_score
from classic_voice import render_engine
from clock24 import Clock24, PulseTransport
from tb303_rt import RealtimeEngine

from live_controls import LiveControls
from live_pattern import DIVISIONS as SCALES
MODES={"Forward":"forward","Reverse":"reverse","Fwd&Rev":"fwd_rev","Invert":"invert","Random":"random"}


def edit(title):
    def deco(fn):
        @wraps(fn)
        def call(self,*a,**kw):
            with self._editing(title):
                return fn(self,*a,**kw)
        return call
    return deco



class ClassicControls(LiveControls):
    def _classic_boot(self):
        self.patterns=[None]*SLOTS
        self.patterns[0]=Pattern.from_grid(self.steps)
        self.tracks=[Track() for _ in range(TRACKS)]
        self.profile="classic"
        self.editor="Grid"
        self.face_track=False
        self.pc=self.track_no=self.bar_pos=0
        self.hist=History()
        self._nested=0; self._ready=False
        self._gesture=None; self._gesture_job=None
        self._live=self._live_host=self._pending_bank=None
        self._live_initial_iid=None
        self._track_player=None; self._track_host=None; self._classic_win=None
        self._combo_seen={}; self._export_job=None
        self._play_cells=[]; self._play_bounds=[]
        self._tap_times=None
        self._random_orders={}
        self.midi_clock=Clock24()

    def _pat(self):
        b=self.cur_bank
        if self.patterns[b] is None:
            self.patterns[b]=Pattern.from_grid(self.banks[b] or [])
        return self.patterns[b]

    def _history_state(self):
        self._freeze_bank()
        return {"data":deepcopy((self.banks,self.bank_settings,self.bank_instr,
                  [None if p is None else p.dump() for p in self.patterns],
                  [t.dump() for t in self.tracks],self.profile,self.preset_v.get())),
                "where":(self.cur_bank,self.sel,self.pc,self.track_no,self.bar_pos,self.editor,self.face_track)}

    @contextmanager
    def _editing(self,title):
        if not getattr(self,"_ready",False) or self._nested:
            yield
            return
        self._finish_gesture()
        before=self._history_state()
        self._nested+=1
        try:
            yield
        except Exception:
            raise
        else:
            self.hist.commit(before,self._history_state(),title)
        finally:
            self._nested-=1
            self._controls_refresh()

    def _begin_gesture(self,k,delayed=False):
        if not self._ready: return
        if self._gesture is None or self._gesture[0]!=k:
            self._finish_gesture()
            self._gesture=(k,self._history_state())
        if self._gesture_job:
            self.root.after_cancel(self._gesture_job)
            self._gesture_job=None
        if delayed:
            self._gesture_job=self.root.after(350,self._finish_gesture)

    def _finish_gesture(self):
        if self._gesture_job:
            self.root.after_cancel(self._gesture_job)
            self._gesture_job=None
        if self._gesture:
            key,old=self._gesture
            self._gesture=None
            self.hist.commit(old,self._history_state(),key)
            self._controls_refresh()

    def _release_knob(self,event=None):
        self._drag=None
        self._finish_gesture()

    def history_move(self,redo=False):
        self._finish_gesture()
        item=self.hist.move(redo)
        if item is None: return
        title,snap=item
        was_pattern=self._playing_internal_pattern()
        self._stop()
        self._nested+=1
        try:
            banks,settings,voices,patterns,tracks,self.profile,preset=deepcopy(snap["data"])
            b,sel,pc,self.track_no,self.bar_pos,mode,face_track=snap["where"]
            self.banks,self.bank_settings,self.bank_instr=banks,settings,voices
            self.patterns=[Pattern.read(p) if p is not None else None for p in patterns]
            self.tracks=[Track.read(t) for t in tracks]
            self.preset_v.set(preset)
            self._enter_bank(b)
            self.sel,self.pc,self.editor,self.face_track=sel,pc,mode,face_track
            if was_pattern: self._toggle_run()
            self.last_action=("Redone: " if redo else "Undone: ")+title
            self.refresh()
        finally:
            self._nested-=1
            self._controls_refresh()

    def _select_combo(self,name):
        var={"preset":self.preset_v,"scale":self.scale_v,"playmode":self.playmode_v}[name]
        new=var.get(); old=self._combo_seen.get(name,new)
        var.set(old)
        with self._editing(name):
            var.set(new)
            if name=="preset": self._apply_preset(new)
            else: self._changed()

    def _classic_menu(self,menubar):
        from classic_panel import install_menu
        install_menu(self,menubar)

    def _controls_refresh(self):
        if hasattr(self,"_face"): self._face.sync()
        if self._classic_win is not None and self._classic_win.winfo_exists(): self._classic_win.sync()
        self._combo_seen={"preset":self.preset_v.get(),"scale":self.scale_v.get(),"playmode":self.playmode_v.get()}

    def show_classic(self,tab=0):
        from classic_panel import ClassicPanel
        if self._classic_win is None or not self._classic_win.winfo_exists():
            self._classic_win=ClassicPanel(self)
        self._classic_win.show(tab)

    def mode_select(self,mode):
        self._finish_gesture()
        self.face_track=False; self.editor=mode; self.pc=self.sel=0; self._tap_times=None
        self.refresh()

    def cursor(self,pos):
        self._finish_gesture()
        if self.editor=="Pitch":
            self.pc=pos%16
            cells=[i for i,k in enumerate(self._pat().time[:self._pat().length]) if k=="N"]
            self.sel=cells[self.pc] if self.pc<len(cells) else min(self.pc,self._pat().length-1)
        else:
            self.sel=pos%self._pat().length
        self.refresh()

    def navigate(self,direction):
        self.cursor((self.pc if self.editor=="Pitch" else self.sel)+direction)

    def _paint_pattern(self):
        self.steps=self._pat().grid()
        self.sel=min(self.sel,self._pat().length-1)
        self._changed()

    @edit("Note")
    def _set_note(self,note,accent=None,slide=None,legato_from=False):
        p=self._pat()
        if self.editor=="Time":
            self.time_write("R" if note is None else "N")
            return
        if self.editor=="Pitch":
            if note is None: return  # rhythm belongs to Time
            if legato_from and 0<self.pc<=len(p.pitches):
                p.pitches[self.pc-1]["slide"]=True
            p.write_pitch(self.pc,note,accent,slide)
            self._preview(note); self._paint_pattern(); self.navigate(1)
            return
        if legato_from:
            prev=self.steps[(self.sel-1)%p.length]
            if prev["note"]: prev["slide"]=True
        cell=self.steps[self.sel]
        cell.pop("tie",None); cell.pop("on",None)
        cell["note"]=note
        if accent is not None: cell["accent"]=accent
        if slide is not None: cell["slide"]=slide
        p.replace_grid(self.steps)
        self._preview(note); self.sel=(self.sel+1)%p.length; self._paint_pattern()

    @edit("Accent / Slide")
    def _toggle_step(self,key):
        p=self._pat()
        if self.editor=="Pitch":
            if self.pc>=len(p.pitches): p.write_pitch(self.pc,None)
            cell=p.pitches[self.pc]
            cell[key]=not cell[key]
        else:
            row=self.steps[self.sel]
            row[key]=not row[key]
            p.replace_grid(self.steps)
        self._paint_pattern()

    @edit("Transposition")
    def transpose(self,semitones,whole=False):
        p=self._pat()
        if whole:
            for n in p.pitches: n["note"]=transposed(n["note"],semitones)
        elif self.editor=="Pitch":
            if self.pc<len(p.pitches):
                n=p.pitches[self.pc]; n["note"]=transposed(n["note"],semitones)
        else:
            n=self.steps[self.sel]; n["note"]=transposed(n["note"],semitones)
            p.replace_grid(self.steps)
        self._paint_pattern()

    def _octave(self,d): self.transpose(12*d)

    @edit("Pattern length")
    def set_length(self,n):
        self._pat().length=between(n,1,16,"length")
        self._paint_pattern()

    @edit("Timing: note, tie or rest")
    def time_write(self,kind):
        p=self._pat(); p.write_time(self.sel,kind)
        self.sel=(self.sel+1)%p.length
        self._paint_pattern()

    @edit("Insert or delete a step")
    def shift_step(self,insert):
        self._pat().shift_cell(self.sel,insert)
        self._paint_pattern()

    @edit("Clear pattern")
    def _clear(self):
        self.patterns[self.cur_bank]=Pattern()
        self.pc=self.sel=0
        self._paint_pattern()

    @edit("Load demo pattern")
    def _demo(self):
        self.patterns[self.cur_bank]=Pattern.from_grid(DEMO_PATTERN)
        self.pc=self.sel=0
        self._paint_pattern()

    @edit("Sound profile")
    def voice_profile(self,which):
        if which not in ("classic","legacy"): return
        self.profile=which; self._changed()

    def tap(self):
        if self._track_player is not None:
            self._track_player.request("ds"); return
        if self._tap_times is not None:
            self._tap_record_hit(); return
        p=self._pat()
        if self.editor=="Pitch":
            if self.pc<len(p.pitches): self._preview(p.pitches[self.pc]["note"])
        else:
            self._preview(self.steps[self.sel].get("note"))
        self.navigate(1)

    def write_next(self):
        # In the pattern editor: verify/advance without changing a stored note.
        self.tap()

    def bar_reset(self):
        if self._live is not None and self._live.clock is not None:
            self.cancel_live_request();self.pc=self.sel=self.bar_pos=0;self.refresh();return
        if self._track_player is not None:
            self._track_player.request("reset")
        else:
            self.pc=self.sel=self.bar_pos=0
            if self.playing:
                self._stop(); self._toggle_run()
            self.refresh()

    def tap_arm(self):
        # First tap defines the downbeat. Commit a complete pass with one Undo.
        self._tap_times=None if self._tap_times is not None else []
        self.refresh()

    def _tap_record_hit(self):
        taps=self._tap_times
        now=time.monotonic()
        taps.append(now)
        self.refresh()

    @edit("Tap rhythm")
    def tap_commit(self):
        taps,self._tap_times=self._tap_times,None
        if not taps: self.refresh(); return
        p=self._pat(); dur=60./self.kv["bpm"]/SCALES[self.scale_v.get()]
        starts=[0.]
        for i in range(p.length):
            starts.append(starts[-1]+dur*(1+self.kv["shuffle"]*(-1)**i))
        hits={min(range(p.length),key=lambda i: abs(starts[i]-(t-taps[0])))
              for t in taps if t-taps[0]<starts[-1]}
        for i in range(p.length): p.write_time(i,"N" if i in hits else "R")
        self._paint_pattern()

    def _ordered(self,slot=None,shift=0,mode=None):
        slot=self.cur_bank if slot is None else slot
        pat=self.patterns[slot] or Pattern.from_grid(self.banks[slot] or [])
        mode=self.playmode_v.get() if mode is None else mode
        seq=[dict(s,cell=i,note=transposed(s["note"],shift)) for i,s in enumerate(pat.grid(True))]
        if mode=="Random":
            key=(slot,len(seq))
            if key not in self._random_orders:
                self._random_orders[key]=np.random.default_rng().permutation(len(seq))
            return [seq[i] for i in self._random_orders[key]]
        return apply_play_mode(seq,MODES[mode])

    @staticmethod
    def _clock_boundaries(length,sr,bpm,div,swing):
        t=sr*60./bpm/div
        return tuple(np.cumsum([t*(1+swing*(-1)**i) for i in range(length)]))

    def _order_live(self):
        seq=self._ordered()
        self._play_cells=[s["cell"] for s in seq]
        self._play_bounds=self._clock_boundaries(len(seq),self.SR,self.kv["bpm"],SCALES[self.scale_v.get()],self.kv["shuffle"])
        return seq

    def _render_profile(self,repeats=1,note=None):
        e=RealtimeEngine(sr=self.SR)
        self._push_rt(e)
        if note is not None:
            e.set_pattern([note]); e.set_param("bpm",80); e.set_param("subdiv",1); e.set_param("swing",0.)
        return render_engine(e,repeats)

    @edit("Edit track")
    def track_edit(self,action,slot=None,shift=0):
        t=self.tracks[self.track_no]; pos=min(len(t.bars),self.bar_pos)
        if action in ("write","insert"):
            t.put(pos,self.cur_bank if slot is None else slot,shift,action=="insert")
            self.bar_pos=min(63,len(t.bars),pos+1) if action=="write" else pos
        elif action=="delete" and pos<len(t.bars):
            t.remove(pos); self.bar_pos=min(pos,len(t.bars))
        elif action in ("dc","segno") and pos<len(t.bars):
            t.mark(action,None if getattr(t,action)==pos else pos)
        self.refresh()

    def _score(self,track=None):
        self._freeze_bank()
        # Build independent voices on the GUI thread; the sample clock reads no Tk variables.
        return Score(self.tracks[self.track_no] if track is None else track,
                     lambda slot,shift:self._program(slot,shift,inherit=False).make_bar(),self.SR)

    def chain_play(self,start,end):
        group=self.cur_bank//8*8
        t=Track()
        for i in range(start,end+(1 if end>=start else -1),1 if end>=start else -1):
            t.put(len(t.bars),group+i)
        self.track_play(t)

    def track_play(self,track=None,start_at=0):
        if self._track_player is not None:
            self._stop(); return
        if not (self.tracks[self.track_no] if track is None else track).bars:
            messagebox.showinfo("Track Play","Write at least one bar with WRITE / NEXT.",parent=self.root); return
        try:
            self._stop()
            score=self._score(track)
            host=self._active_engine()
            if host is not None and host.stream is not None and host.stream.active:
                player=Transport(score,start_at=start_at)
                # Prime possible JIT signatures off the audio thread.
                for b in score.bars:
                    b.engine.process(np.empty(0))
                self._track_player=player; self._track_host=host
                with host._lock: host.track_source=player
            else:
                if not self._ensure_pygame(): raise RuntimeError("Audio output is unavailable. You can still export a WAV file.")
                import pygame
                photo=getattr(self,"_roland_view",None)
                if photo is not None and photo.visible:
                    from roland_audio import TrackOutput
                    self._track_player=TrackOutput(score,pygame,start_at=start_at)
                else:self._track_player=MixerTrack(score,pygame,start_at=start_at)
            self.playing=True; self._vu_start(); self.refresh()
        except Exception as exc:
            self._track_stop(); messagebox.showerror("Track Play",str(exc),parent=self.root)

    def sync_arm(self,track_mode=False):
        if self._track_player is not None:
            self._stop()
        if getattr(self,"midi",None) is None:
            messagebox.showinfo("MIDI Clock","No MIDI input is open. Connect your MIDI device and restart the Studio.",parent=self.root)
            return
        host=self._active_engine()
        if host is None or host.stream is None or not host.stream.active:
            messagebox.showinfo("MIDI Clock","External sync requires the real-time audio engine (sounddevice and numba).",parent=self.root)
            return
        try:
            self._stop()
            if not track_mode:
                self.midi_clock=Clock24()
                self._start_live(self.midi_clock)
                return
            score=self._score(self.tracks[self.track_no])
            for b in score.bars: b.engine.process(np.empty(0))
            self.midi_clock=Clock24()
            player=PulseTransport(score,self.midi_clock)
            self._track_host=host; self._track_player=player
            with host._lock: host.track_source=player
            self.playing=True; self._vu_start(); self.refresh()
        except (ValueError,RuntimeError) as exc:
            self._track_stop(); messagebox.showerror("MIDI Clock",str(exc),parent=self.root)

    def _track_stop(self):
        host=self._track_host
        if host is not None:
            with host._lock: host.track_source=None
        player=self._track_player
        if isinstance(player,MixerTrack): player.stop()
        self._track_host=self._track_player=None

    def export_track(self):
        if self._export_job is not None: return
        if not self.tracks[self.track_no].bars:
            messagebox.showinfo("Export track","The track is empty.",parent=self.root); return
        path=filedialog.asksaveasfilename(parent=self.root,title="Export track (one pass)",
              initialfile=f"track_{self.track_no+1}.wav",defaultextension=".wav",filetypes=[("WAV","*.wav")])
        if not path: return
        try: score=self._score()
        except Exception as exc:
            messagebox.showerror("Export track",str(exc),parent=self.root); return
        job=self._export_job={}; self._busy="Exporting track…"; self.refresh()
        def run():
            try: export_score(score,path)
            except Exception as exc: job["error"]=str(exc)
            finally: job["done"]=True
        Thread(target=run,daemon=True).start()
        def poll():
            if not job.get("done"): self.root.after(100,poll); return
            self._export_job=None; self._busy=None; self.refresh()
            if "error" in job: messagebox.showerror("Export track",job["error"],parent=self.root)
            else: messagebox.showinfo("Export complete",str(path),parent=self.root)
        self.root.after(100,poll)

