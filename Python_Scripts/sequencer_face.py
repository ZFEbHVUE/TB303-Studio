"""A real control surface on the same canvas as the keyboard. No modal editor."""
from PIL import Image, ImageTk
from tkinter import font as tkfont
from face_layout import WIDTH, SOURCE_HEIGHT, SEAM, BAY, ART, KEYS, LCD, hit
from build_face_skins import FILM_TOP, FILM_END, PACK_SIZE, STYLE, build, state_box
from classic_sequence import label, BARS

RESAMPLE = getattr(Image,"Resampling",Image).LANCZOS
def compose(original, skin):
    """Install one continuous illustrated chassis. Only moving keys need sprites."""
    if original.size != (WIDTH,SOURCE_HEIGHT):
        raise ValueError("Unexpected source dimensions for the inlaid chassis.")
    if skin=="custom":
        return build(original,skin)
    with Image.open(ART/skin/"inlay.png") as f, Image.open(ART/skin/"switches.png") as a:
        if f.size!=(WIDTH,FILM_END+BAY-FILM_TOP) or a.size!=PACK_SIZE:
            raise ValueError("Unexpected factory skin dimensions: "+skin)
        film=f.convert("RGB"); moving=a.convert("RGB")
    case=Image.new("RGB",(WIDTH,SOURCE_HEIGHT+BAY))
    case.paste(original.crop((0,0,WIDTH,FILM_TOP)),(0,0))
    case.paste(film,(0,FILM_TOP))
    case.paste(original.crop((0,FILM_END,WIDTH,SOURCE_HEIGHT)),(0,FILM_END+BAY))
    return case,moving

class SequencerFace:
    def __init__(self, app, atlas):
        self.a=app
        self.cv=app.cv
        self.notice=None
        self.notice_job=None
        self.hand=False
        self.mount(atlas)

    def mount(self, atlas):
        self.cv.delete("inlay")
        self.atlas=atlas
        self.photos={}
        self.states={}
        self.pressed=self.over=None
        self.captured=False
        self.texts=None
        self.items={}
        a=self.a
        for key in KEYS.values():
            x,y,_,_=key.box
            self.items[key.id]=self.cv.create_image(round(a.S(x)),round(a.S(y+SEAM)),
                         anchor="nw",state="hidden",tags=("inlay","inlay_"+key.id))
        lx,ly,rx,ry=LCD
        ink = "#"+STYLE.get(a._skin,STYLE["steampunk"])[2]
        self.lines=[]
        family=tkfont.nametofont("TkFixedFont",root=a.root).actual("family")
        for yy,px,color in ((ly+18,19,ink),(ly+38,14,ink)):
            self.lines.append(self.cv.create_text(round(a.S(((lx+rx)/2))),round(a.S(SEAM+yy)),
                   font=(family,-max(7,round(a.S(px))),"bold"),fill=color,
                   tags=("inlay","inlay_display")))
        self.sync()

    def paint(self, ident, state):
        if self.states.get(ident)==state: return
        self.states[ident]=state
        item=self.items[ident]
        if not state:
            self.cv.itemconfigure(item,state="hidden"); return
        slot=(ident,state)
        if slot not in self.photos:
            x,y,X,Y=KEYS[ident].box; S=self.a.S
            size=(max(1,round(S(X))-round(S(x))),max(1,round(S(SEAM+Y))-round(S(SEAM+y))))
            cap=self.atlas.crop(state_box(KEYS[ident],state)).resize(size,RESAMPLE)
            self.photos[slot]=ImageTk.PhotoImage(cap,master=self.cv)
        self.cv.itemconfigure(item,image=self.photos[slot],state="normal")

    def sync(self):
        a=self.a
        enabled={a.editor.lower()} if not a.face_track else {"track_write"}
        if a.hist.past: enabled.add("back")
        if a.hist.future: enabled.add("redo")
        if a._track_player is not None: enabled.add("track_play")
        if a._tap_times is not None: enabled.add("tap")
        if a.editor=="Time" and not a.face_track:
            enabled.add({"N":"note","T":"tie","R":"rest"}[a._pat().time[a.sel]])
        for ident in KEYS:
            self.paint(ident, 2 if ident==self.pressed and ident==self.over else int(ident in enabled))
        self.readout()

    def readout(self):
        a=self.a
        at=a.pc if a.editor=="Pitch" else a.sel
        position=f"PITCH {at+1:02}/16" if a.editor=="Pitch" else f"STEP {at+1:02}/{a._pat().length:02}"
        top=f"{label(a.cur_bank)}  {position}"
        player=a._track_player
        if a._live is not None and not a.face_track:
            top=f"{label(a.cur_bank)}  STEP {a._live.heard_cell()+1:02}/{a._pat().length:02}"
        if a._pending_bank is not None:
            detail="NEXT: "+label(a._pending_bank)
        elif self.notice:
            detail=self.notice
        elif a._live is not None and a._live.clock is not None:
            detail="MIDI · WAITING" if a._live.pulse.waiting else "MIDI · PATTERN"
        elif player is not None:
            if getattr(player,"waiting",False):
                detail="MIDI · WAITING START"
            elif getattr(player,"started",True) is None:
                detail="PREPARING AUDIO"
            else:
                detail=f"PLAY T{a.track_no+1} · BAR {player.index+1:02}"
        elif a.face_track:
            n=len(a.tracks[a.track_no].bars)
            detail=f"T{a.track_no+1} · BAR {min(a.bar_pos+1,BARS):02} / {n:02}"
        else:
            wording={"Grid":"GRID","Pitch":"PITCH","Time":"TIME"}[a.editor]
            detail=f"{wording}  ·  {a.profile.upper()}"
        new=(top,detail)
        if self.texts != new:
            for item,msg in zip(self.lines,new): self.cv.itemconfigure(item,text=msg)
            self.texts=new

    def say(self, msg):
        self.clear_notice()
        self.notice=msg
        self.readout()
        def reset():
            self.notice_job=None
            self.notice=None
            self.readout()
        self.notice_job=self.a.root.after(2300,reset)

    def clear_notice(self):
        if self.notice_job is not None:
            self.a.root.after_cancel(self.notice_job)
            self.notice_job=None
        self.notice=None

    def close(self):
        self.clear_notice()

    def position(self,e):
        x,y=self.a._to_img(e)
        return hit(x,y-SEAM)

    def press(self,e):
        ident=self.position(e)
        if ident is None:
            return False
        self.captured=True
        self.pressed=self.over=ident
        self.sync()
        return True

    def move(self,e):
        ident=self.position(e)
        if self.captured and self.over!=ident:
            self.over=ident; self.sync()
        if bool(ident)!=self.hand:
            self.hand=bool(ident)
            self.cv.configure(cursor="hand2" if self.hand else "")

    def release(self,e):
        if not self.captured: return False
        key=self.pressed if self.pressed==self.position(e) else None
        self.captured=False; self.pressed=self.over=None
        self.sync()
        if key:
            self.clear_notice()
            self.dispatch(key)
            self.a._controls_refresh()
        return True

    def dispatch(self,k):
        a=self.a
        if k in ("back","redo"):
            redo=k=="redo"
            if not (a.hist.future if redo else a.hist.past):
                self.say("NOTHING TO REDO" if redo else "NOTHING TO UNDO")
            else:
                a.history_move(redo)
        elif k in ("prev","next"): a.navigate(-1 if k=="prev" else 1)
        elif k in ("grid","pitch","time"): a.mode_select(k.title())
        elif k in ("note","tie","rest"):
            # A direct timing key belongs to the step that is already selected.
            # A mode-button press starts a pass at step 1; this shortcut must not.
            if a.editor!="Time" or a.face_track:
                a._finish_gesture(); a.face_track=False; a.editor="Time"; a._tap_times=None
            a.time_write({"note":"N","tie":"T","rest":"R"}[k])
        elif k in ("ins","del","write"):
            if a.face_track:
                bars=a.tracks[a.track_no].bars
                pos=min(a.bar_pos,len(bars))
                if len(bars)>=BARS and (k=="ins" or (k=="write" and pos==len(bars))):
                    self.say("TRACK FULL"); return
                if k=="del" and pos==len(bars): self.say("EMPTY BAR"); return
                # Replacing an existing bar keeps its transpose; new bars start at zero.
                shift=bars[pos][1] if k=="write" and pos<len(bars) else 0
                a.track_edit({"write":"write","ins":"insert","del":"delete"}[k],shift=shift)
            elif k=="write":
                if a._tap_times is not None: a.tap_commit()
                else: a.write_next()
            else: a.shift_step(k=="ins")
        elif k in ("shorter","longer"):
            length=a._pat().length
            n=max(1,min(16,length+(1 if k=="longer" else -1)))
            if n!=length: a.set_length(n)
        elif k=="tap": a.tap()
        elif k=="track_write":
            a._finish_gesture(); a.face_track=True; a._tap_times=None
        elif k=="track_play":
            a.face_track=True
            if a._track_player is None and not a.tracks[a.track_no].bars:
                self.say("EMPTY: WRITE / NEXT")
            else: a.track_play()
        elif k=="reset": a.bar_reset()
        elif k in ("bar_prev","bar_next"):
            a.face_track=True
            end=min(BARS-1,len(a.tracks[a.track_no].bars))
            a.bar_pos=max(0,min(end,a.bar_pos+(-1 if k=="bar_prev" else 1)))
            a._controls_refresh()
        elif k in ("group","section"):
            b=a._selector_slot()
            a._switch_bank((((b//16+1)%4)*16+b%16) if k=="group" else b^8)
        elif k=="track":
            if a._track_player is not None: a._stop()
            a.face_track=True; a.track_no=(a.track_no+1)%len(a.tracks); a.bar_pos=0
            a._controls_refresh()

