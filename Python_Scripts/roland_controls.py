"""Operation of the photographed switches; the Studio owns the musical data."""
import time
from tb303 import midi_to_name,name_to_midi
from roland_geometry import WHITES,PITCH_KEYS,MOD_KEYS,GROUPS

TIME_CODES={"down":"N","up":"T","accent_key":"R"}
TIME_LENS={v:k for k,v in TIME_CODES.items()}
BASE_NOTE=48                      # C3, with A3 at 220 Hz for A440 tuning

class PanelControls:
    def __init__(self,app):
        self.a=app;self.mode=2;self.group=0
        self.held=set();self.used=set();self.feedback=None;self.until=0.
        self.review=None;self.review_key=None;self.step_count=0;self.digits=[]
        self.chain=None;self.chain_running=False
        self.marker=None;self.bar_shift=0;self.insert_bar=False
        self.epoch=time.monotonic();self.power=True;self.last_volume=.9
        self._mode_from_app()

    def _mode_from_app(self):
        a=self.a
        if a.face_track:
            if self.mode>=2:self.mode=1 if a._track_player is not None else 0
        elif a.editor in ("Pitch","Time"):
            self.mode=3
        elif self.mode<2:
            self.mode=2
        if self.mode<2:self.group=a.track_no
        elif GROUPS[self.group]!=a._selector_slot()//16:
            self.group=min(6,2*(a._selector_slot()//16))

    def reset_holds(self):
        self.held.clear();self.used.clear();self.review=self.review_key=None
        self.feedback=None;self.step_count=0;self.digits.clear()

    def show(self):
        self._mode_from_app();self.reset_holds();self.epoch=time.monotonic()

    def power_set(self,on):
        a=self.a;on=bool(on)
        if on==self.power:return
        if not on:
            self.last_volume=a.kv["volume"] or self.last_volume
            if a.playing:a._stop()
            a.kv["volume"]=0.
        else:a.kv["volume"]=self.last_volume
        self.power=on;self.reset_holds();a._knob_live("volume")

    def set_mode(self,i):
        if not self.power or self.mode==i:return
        a=self.a
        if a.playing:a._stop()
        self.set_shift(0);self.chain=None;self.chain_running=False;self.marker=None;self.insert_bar=False
        self.bar_shift=0;self.reset_holds();self.mode=i
        a.mode_select("Grid")
        if i<2:
            a.face_track=True;a.track_no=self.group;a.bar_pos=0
            self.recall_bar()
        else:self.select_slot(GROUPS[self.group]*16+a._selector_slot()%16)
        a.refresh()

    def set_group(self,i):
        if not self.power or i==self.group:return
        a=self.a
        if self.mode==2 and a.playing:return
        self.group=i
        if self.mode<2:
            if a.playing:a._stop()
            a.track_no=i;a.bar_pos=0;self.recall_bar()
        else:self.select_slot(GROUPS[i]*16+a._selector_slot()%16)
        a.refresh()

    def set_shift(self,shift):
        a=self.a;a._panel_shift=shift
        if a._live is not None:
            if self.chain and self.chain_running:
                self.stage_chain();return
            goal=a._selector_slot()
            a._live.request(a._program(goal,shift=shift))
            a._poll_live()

    def recall_bar(self):
        a=self.a;bars=a.tracks[a.track_no].bars
        if 0<=a.bar_pos<len(bars):
            slot,self.bar_shift=bars[a.bar_pos];a._switch_bank(slot)
        else:self.bar_shift=0

    def select_slot(self,slot):
        a=self.a
        if self.mode==2 and slot!=a._selector_slot():
            self.bar_shift=0;a._panel_shift=0
        if self.mode==2 and a._live is not None:
            a._live.queue_playlist([a._program(slot,shift=a._panel_shift)],finish_series=True)
            a._poll_live()
        else:a._switch_bank(slot)
        self.feedback=None

    def schedule_chain(self,start,end):
        a=self.a
        if start//4!=end//4:return
        self.chain=(min(start,end),max(start,end))
        if a._live is not None:
            self.stage_chain()
        elif not a.playing:a._switch_bank(self.chain[0])

    def stage_chain(self):
        a=self.a
        specs=[a._program(slot,shift=a._panel_shift) for slot in range(self.chain[0],self.chain[1]+1)]
        a._live.queue_playlist(specs,finish_series=True)
        self.chain_running=len(specs)>1

    def start_chain(self):
        a=self.a;a._switch_bank(self.chain[0]);a._toggle_run()
        if a._live is not None:self.stage_chain()

    def run(self):
        a=self.a
        if a.playing:
            a._stop();self.chain_running=False
            if self.mode==3 and a._tap_times is not None:a.tap_commit()
            return
        if self.mode==1:
            if a.tracks[a.track_no].bars:a.track_play(start_at=min(a.bar_pos,a.tracks[a.track_no].end))
        elif self.mode==2 and self.chain and self.chain[0]!=self.chain[1]:
            self.start_chain()
        else:a._toggle_run()

    def show_note(self,index,name):
        self.review=index;self.review_key=name;self.feedback=("pitch",index)
        self.until=time.monotonic()+.20

    def pitch_key(self,k):
        a=self.a;idx=PITCH_KEYS.index(k)
        octaves=int("up" in self.held)-int("down" in self.held)
        if {"up","down"}<=self.held:octaves=-2
        note=midi_to_name(BASE_NOTE+idx+12*octaves);p=a.pc
        a._set_note(note,accent="accent_key" in self.held,slide="slide" in self.held)
        self.show_note(p,k)

    def tap_note(self):
        a=self.a;p=a._pat()
        if a.editor=="Pitch":
            idx=a.pc
            if idx<len(p.pitches):
                a._preview(p.pitches[idx]["note"]);self.show_note(idx,"write")
            a.navigate(1)
        else:
            idx=a.sel;self.feedback=("time",p.time[idx]);self.until=time.monotonic()+.20
            self.review_key="write";a.navigate(1)
            if a.sel==0:a.mode_select("Grid")

    def modify_review(self,k):
        a=self.a
        if self.review is None:return
        p=a._pat()
        if self.review>=len(p.pitches):return
        with a._editing("Pitch properties"):
            row=p.pitches[self.review]
            if k in ("accent_key","slide"):
                attr="accent" if k=="accent_key" else "slide";row[attr]=not row[attr]
            elif row["note"]:
                m=name_to_midi(row["note"]);m=max(0,min(127,m+(12 if k=="up" else -12)))
                row["note"]=midi_to_name(m)
            a._paint_pattern()

    def write_timing(self,k):
        a=self.a;code=TIME_CODES[k];last=a.sel==a._pat().length-1
        a.time_write(code);self.feedback=("time",code);self.review_key=k;self.until=time.monotonic()+.16
        if last:a.mode_select("Grid")

    def clear_pattern(self):
        # The hardware erases timing and resets the step system; its pitch RAM
        # survives. Studio's separate Clear command keeps its usual behaviour.
        a=self.a
        with a._editing("Clear timing"):
            p=a._pat();p.time[:]=["R"]*16;p.flags.clear();p.length=16
            a.pc=a.sel=0;a.scale_v.set("1/16");a._paint_pattern()
        self.feedback=None

    def write_bar(self):
        a=self.a;t=a.tracks[a.track_no];pos=min(a.bar_pos,len(t.bars))
        if pos>=64 or (self.insert_bar and len(t.bars)>=64):return
        with a._editing("Write track bar"):
            slot=a._selector_slot()
            t.put(pos,slot,self.bar_shift,self.insert_bar);self.insert_bar=False
            if self.marker=="dc":
                if t.segno is not None and t.segno>=pos:t.mark("segno",None)
                t.mark("dc",pos)
            if self.marker=="segno" and (t.dc is None or pos<t.dc):t.mark("segno",pos)
            self.marker=None;a.bar_pos=min(63,pos+1)
            self.recall_bar();a.refresh()

    def func_action(self,k):
        a=self.a
        if self.mode<2:
            if k in ("cs","ds") and self.mode==0 and not a.playing:
                if k=="cs":a.track_edit("delete");self.recall_bar()
                else:self.insert_bar=True
            elif k in WHITES+MOD_KEYS:
                value=(list(WHITES)+list(MOD_KEYS)).index(k)+1
                number={10:0,11:100,12:200}.get(value,value)
                if len(self.digits)<3:self.digits.append(number)
                bar=0
                for d in self.digits:bar=(bar+d if d>=100 else
                    (bar//100*100+(bar%100)*10+d))
                if not a.playing:
                    a.bar_pos=max(0,min(63,len(a.tracks[a.track_no].bars),bar-1));self.recall_bar()
        elif self.mode==3 and not a.playing and k in ("down","up"):
            with a._editing("Step system"):
                p=a._pat()
                if k=="up":
                    a.scale_v.set("1/8T");p.length=12
                else:
                    limit=15 if a.scale_v.get()=="1/8T" else 16
                    self.step_count=min(limit,self.step_count+1);p.length=self.step_count
                p.time[:]=["R"]*16;p.flags.clear();a.sel=0;a._paint_pattern()

    def normal_key(self,k):
        a=self.a
        if k in ("accent_key","slide"):
            self.chain=None
            slot=a._selector_slot();self.select_slot((slot//16)*16+8*int(k=="slide")+slot%8)
        elif k in WHITES:
            slot=a._selector_slot()//8*8+WHITES.index(k)
            other=next((n for n in WHITES if n!=k and n in self.held),None)
            if self.mode==2 and other:
                self.schedule_chain(slot//8*8+WHITES.index(other),slot)
            else:
                self.chain=None;self.chain_running=False
                self.select_slot(slot)

    def press(self,k):
        if not self.power or k in self.held:return
        a=self.a;self.held.add(k)
        if k=="run":self.run();return
        if k=="func":
            self.step_count=0;self.digits=[]
            return
        if "func" in self.held:
            self.used.add("func");self.func_action(k);return
        if k=="clear":
            if self.mode==3 and not a.playing and any(n in self.held for n in WHITES):
                self.clear_pattern()
            elif self.mode==3 and a.playing:
                a._tap_times=[];self.feedback=None
            elif self.mode==0 and a.playing:self.marker="dc"
            elif self.mode<2:
                running=a._track_player is not None
                a.bar_reset()
                if not running:self.recall_bar()
            return
        if k=="pitch":
            if self.mode==3 and not a.playing:a.mode_select("Pitch");self.feedback=None
            return
        if k=="time":
            if self.mode==3 and not a.playing:a.mode_select("Time");self.feedback=None
            return
        if k=="back":
            if self.mode==0 and a.playing:self.marker="segno"
            elif self.mode==0:a.bar_pos=max(0,a.bar_pos-1);self.recall_bar()
            elif self.mode==3 and not a.playing and a.editor in ("Time","Pitch"):
                a.cursor(max(0,(a.pc if a.editor=="Pitch" else a.sel)-1));self.feedback=None
            return
        if k in PITCH_KEYS and "pitch" in self.held and self.mode!=3:
            self.used.add("pitch");self.bar_shift=PITCH_KEYS.index(k)
            if self.mode in (0,2) and a.playing:self.set_shift(self.bar_shift)
            return
        if k=="write":
            if self.mode==0:self.write_bar()
            elif self.mode==1:
                if a._track_player:a._track_player.request("ds")
                elif "pitch" in self.held:a._preview(midi_to_name(BASE_NOTE+self.bar_shift))
                else:
                    a.bar_pos=min(len(a.tracks[a.track_no].bars),63,a.bar_pos+1);self.recall_bar()
            elif self.mode==3 and a.playing and a._tap_times is not None:a._tap_record_hit()
            elif self.mode==3 and a.editor in ("Pitch","Time") and not a.playing:self.tap_note()
            elif not a.playing:a._preview(midi_to_name(BASE_NOTE+self.bar_shift))
            return
        if self.mode==3 and not a.playing and a.editor=="Pitch":
            if k in MOD_KEYS and (self.review_key in self.held or "write" in self.held):self.modify_review(k)
            elif k in PITCH_KEYS:self.pitch_key(k)
        elif self.mode==3 and not a.playing and a.editor=="Time":
            if k in TIME_CODES:self.write_timing(k)
        elif self.mode!=1:self.normal_key(k)

    def release(self,k):
        if k not in self.held:return
        self.held.discard(k)
        if k=="func":
            if k not in self.used and self.mode==3 and not self.a.playing:
                self.a.mode_select("Grid");self.feedback=None
            self.digits=[]
        self.used.discard(k)
        if k==self.review_key:self.review_key=None

    def lamp_ids(self,t):
        a=self.a;self._mode_from_app()
        if not self.power:return set()
        out=set()
        if t.running:out.add("run")
        pos=t.slot;mode=self.mode
        if mode==0 and not a.playing and a.bar_pos<len(a.tracks[a.track_no].bars):
            pos=a.tracks[a.track_no].bars[a.bar_pos][0]
        if mode==1 and a._track_player is None and a.bar_pos<len(a.tracks[a.track_no].bars):
            pos=a.tracks[a.track_no].bars[a.bar_pos][0]
        if mode<2 and "func" in self.held:
            digits=self.digits[:]
            if not digits:
                n=(t.bar if t.running and mode==1 else a.bar_pos)+1
                digits=[int(s) for s in str(n)]
            digit=lambda d:dict(zip((1,2,3,4,5,6,7,8,9,0,100,200),WHITES+MOD_KEYS))[d]
            out.update(digit(i) for i in digits[:-1])
            if t.beat_on:out.add(digit(digits[-1]))
            return out
        if mode==3 and not a.playing and a.editor in ("Pitch","Time"):
            out.add(a.editor.lower())
            if self.feedback and (self.review_key in self.held or time.monotonic()<self.until):
                kind,val=self.feedback
                if kind=="time":out.add(TIME_LENS[val])
                elif val<len(a._pat().pitches):
                    n=a._pat().pitches[val]
                    if n["note"]:
                        p=name_to_midi(n["note"]);offset=p-BASE_NOTE
                        note_i=(12 if offset in (12,24) else offset%12)
                        key=self.review_key
                        if key in PITCH_KEYS and PITCH_KEYS.index(key)%12==note_i%12:note_i=PITCH_KEYS.index(key)
                        out.add(PITCH_KEYS[note_i])
                        octs=(offset-note_i)//12
                        if octs<0:out.add("down")
                        if octs>0 or octs<=-2:out.add("up")
                    if n["accent"]:out.add("accent_key")
                    if n["slide"]:out.add("slide")
            if a.editor=="Pitch":out.update(self.held.intersection(MOD_KEYS))
            return out
        if mode!=3 and "pitch" in self.held:
            shift=t.shift if t.running and mode==1 else self.bar_shift
            out.update(("pitch",PITCH_KEYS[12 if shift==12 else shift%12]));return out
        if mode==3:
            out.add("normal")
            if "func" in self.held:
                if self.step_count:out.add("down")
                if a.scale_v.get()=="1/8T":out.add("up")
                return out
        out.add("slide" if (pos//8)%2 else "accent_key")
        if self.chain and mode==2:
            out.update(WHITES[i%8] for i in self.chain if i!=pos)
        if t.queued is not None and t.queued!=pos:out.add(WHITES[t.queued%8])
        if t.beat_on:out.add(WHITES[pos%8])
        return out
