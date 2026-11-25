"""Nonmodal companion to the existing skins. No original control is covered."""
import tkinter as tk
from tkinter import ttk
import studio_messages as messagebox
from classic_sequence import label


def shortcut(app,fn):
    def run(e):
        if isinstance(e.widget,(tk.Entry,tk.Text,ttk.Entry,ttk.Spinbox)): return None
        fn()
        return "break"
    return run


def install_menu(a,menubar):
    m=tk.Menu(menubar,tearoff=False)
    m.add_command(label="BACK - Undo",accelerator="Ctrl+Z",command=a.history_move)
    m.add_command(label="REDO - Redo",accelerator="Ctrl+Y",command=lambda:a.history_move(True))
    m.add_command(label="Cancel queued pattern",accelerator="Esc",command=a.cancel_live_request)
    m.add_separator()
    m.add_command(label="Classic: Pitch / Time",accelerator="F6",command=a.show_classic)
    m.add_command(label="Track Write / Play",accelerator="F7",command=lambda:a.show_classic(1))
    m.add_command(label="Export track to WAV...",command=a.export_track)
    sm=tk.Menu(m,tearoff=False)
    sm.add_command(label="Arm current pattern",command=lambda:a.sync_arm(False))
    sm.add_command(label="Arm selected track",command=lambda:a.sync_arm(True))
    sm.add_command(label="Use internal clock",command=a._stop)
    m.add_cascade(label="MIDI Clock (24 PPQN)",menu=sm)
    menubar.add_cascade(label="Sequencer",menu=m)
    for key,cmd in (("<Control-z>",a.history_move),("<Control-y>",lambda:a.history_move(True)),
                    ("<Control-Shift-Z>",lambda:a.history_move(True)),
                    ("<Escape>",a.cancel_live_request),("<F6>",a.show_classic),("<F7>",lambda:a.show_classic(1))):
        a.root.bind(key,shortcut(a,cmd),add="+")


class ClassicPanel(tk.Toplevel):
    def __init__(self,app):
        super().__init__(app.root)
        self.a=app
        self.title("TB-303 Studio · Classic Sequencer")
        self.protocol("WM_DELETE_WINDOW",self.withdraw)
        self.resizable(True,True)
        self.columnconfigure(0,weight=1); self.rowconfigure(1,weight=1)
        top=ttk.Frame(self,padding=(10,8,10,2)); top.grid(row=0,column=0,sticky="ew")
        self.group=self._choice(top,"Group",list("1234"),lambda:self._bank(),2)
        self.section=self._choice(top,"Section",list("AB"),lambda:self._bank(),2)
        self.slot=self._choice(top,"Pattern",[str(i) for i in range(1,9)],lambda:self._bank(),2)
        self.prof=self._choice(top,"Sound",["Classic","Legacy"],lambda:app.voice_profile(self.prof.get().lower()),7)
        self.book=ttk.Notebook(self); self.book.grid(row=1,column=0,padx=10,pady=5,sticky="nsew")
        self.p=ttk.Frame(self.book,padding=10); self.t=ttk.Frame(self.book,padding=10)
        self.book.add(self.p,text=" Pattern · Pitch / Time "); self.book.add(self.t,text=" Track Write / Play ")
        self._pattern(); self._track()
        foot=ttk.Frame(self,padding=(10,2,10,8)); foot.grid(row=2,column=0,sticky="ew")
        self._buttons(foot,[("BACK",app.history_move),("REDO",lambda:app.history_move(True)),
                       ("BAR RESET",app.bar_reset)])
        self.detail=ttk.Label(self,anchor="w",padding=(10,0,10,6))
        self.detail.grid(row=3,column=0,sticky="ew")
        for key,fn in (("<Control-z>",app.history_move),("<Control-y>",lambda:app.history_move(True)),
                       ("<Control-Shift-Z>",lambda:app.history_move(True))):
            self.bind(key,shortcut(app,fn),add="+")
        self._last_rows=None
        self.book.bind("<<NotebookTabChanged>>",self._display_tab)
        self.sync()

    def _display_tab(self,_event):
        if self.winfo_viewable():
            self.a.face_track=self.book.index("current")==1
            self.a._face.sync()

    def _choice(self,parent,title,vals,cb,width):
        ttk.Label(parent,text=title).pack(side="left",padx=(3,2))
        var=tk.StringVar(self,value=vals[0])
        box=ttk.Combobox(parent,textvariable=var,values=vals,width=width,state="readonly")
        box.pack(side="left",padx=(0,5))
        box.bind("<<ComboboxSelected>>",lambda e:cb())
        return var

    def _buttons(self,frame,items):
        for title,cmd in items:
            ttk.Button(frame,text=title,command=lambda f=cmd:self._safe(f)).pack(side="left",padx=(0,3),pady=2)

    def _safe(self,cmd):
        try: cmd()
        except (ValueError,IndexError) as exc: messagebox.showinfo("Sequencer",str(exc),parent=self)

    def _bank(self):
        self.a._switch_bank((int(self.group.get())-1)*16+(self.section.get()=="B")*8+int(self.slot.get())-1)

    def _pattern(self):
        a=self.a
        def row():
            frame=ttk.Frame(self.p); frame.pack(fill="x",pady=2); return frame
        r=row()
        self.mode=self._choice(r,"Edit mode",["Grid","Pitch","Time"],lambda:a.mode_select(self.mode.get()),6)
        self.length=self._choice(r,"Length",[str(i) for i in range(1,17)],lambda:a.set_length(int(self.length.get())),3)
        self.clock=self._choice(r,"Grid",["1/16","1/8T","1/8","1/16T","1/32"],self._scale,5)
        self._buttons(row(),[("FUNCTION",lambda:a.mode_select("Grid")),("< PREV",lambda:a.navigate(-1)),("NEXT >",lambda:a.navigate(1)),
                    ("TAP / Check",a.tap),("WRITE / NEXT",a.write_next),("RUN / STOP",a._toggle_run)])
        self.keys=ttk.Label(self.p,wraplength=590,justify="left")
        self.keys.pack(fill="x",pady=(6,3))
        # A second keyboard is useful when the window covers the large skin.
        r=row()
        self.oct=self._choice(r,"Octave",["0","1","2","3","4","5"],lambda:None,2); self.oct.set("2")
        for n in ("C","C#","D","D#","E","F","F#","G","G#","A","A#","B"):
            ttk.Button(r,text=n,width=3,command=lambda note=n:a._set_note(note+self.oct.get())).pack(side="left",padx=1)
        self.pitch_line=ttk.Label(self.p,wraplength=600,justify="left")
        self.pitch_line.pack(fill="x",pady=3)
        r=row()
        self._buttons(r,[("Note",lambda:a.time_write("N")),("Tie",lambda:a.time_write("T")),
                         ("Rest",lambda:a.time_write("R")),("Accent",lambda:a._toggle_step("accent")),
                         ("Slide",lambda:a._toggle_step("slide"))])
        grid=ttk.Frame(self.p); grid.pack(fill="x",pady=3)
        self.cells=[]
        for i in range(16):
            b=ttk.Button(grid,width=6,command=lambda i=i:self._cell(i))
            b.grid(row=i//8,column=i%8,padx=1,pady=1,sticky="ew"); grid.columnconfigure(i%8,weight=1)
            self.cells.append(b)
        self._buttons(row(),[("INS Step",lambda:a.shift_step(True)),("DEL Step",lambda:a.shift_step(False)),
                     ("Note -1",lambda:a.transpose(-1)),("Note +1",lambda:a.transpose(1)),
                     ("Pattern -1",lambda:a.transpose(-1,True)),("Pattern +1",lambda:a.transpose(1,True))])
        r=row()
        self.chainlo=self._choice(r,"Chain patterns from",list("12345678"),lambda:None,2)
        self.chainhi=self._choice(r,"to",list("12345678"),lambda:None,2)
        self.chainhi.set("2")
        self._buttons(r,[("Play / Stop Chain",lambda:a.chain_play(int(self.chainlo.get())-1,int(self.chainhi.get())-1))])
        self._buttons(row(),[("Arm / Cancel Tap",a.tap_arm),("Tap rhythm",a.tap),
                             ("Apply rhythm",a.tap_commit)])
        ttk.Label(self.p,text="Tap the first attack to set the start. Tap the remaining attacks, then select Apply rhythm.").pack(anchor="w")

    def _scale(self):
        self.a.scale_v.set(self.clock.get()); self.a._select_combo("scale")

    def _cell(self,i):
        a=self.a
        if a.editor=="Pitch":
            k=sum(x=="N" for x in a._pat().time[:i]); a.cursor(k)
        else: a.cursor(i)

    def _track(self):
        a=self.a
        r=ttk.Frame(self.t); r.pack(fill="x")
        self.track=self._choice(r,"Track",[str(i) for i in range(1,8)],self._choose_track,2)
        self.shift=self._choice(r,"Transpose (semitones)",[str(i) for i in range(-24,25)],lambda:None,4)
        self.shift.set("0")
        ttk.Label(self.t,text="Select a pattern above, then press WRITE / NEXT to write a bar.").pack(anchor="w",pady=4)
        area=ttk.Frame(self.t); area.pack(fill="both",expand=True)
        self.rows=tk.Listbox(area,height=8,exportselection=False,activestyle="dotbox")
        self.rows.pack(side="left",fill="both",expand=True)
        sb=ttk.Scrollbar(area,orient="vertical",command=self.rows.yview); sb.pack(side="right",fill="y")
        self.rows.configure(yscrollcommand=sb.set); self.rows.bind("<<ListboxSelect>>",self._bar)
        for cmds in [
            [("WRITE / NEXT",lambda:a.track_edit("write",shift=int(self.shift.get()))),
             ("INS Bar",lambda:a.track_edit("insert",shift=int(self.shift.get()))),
             ("DEL Bar",lambda:a.track_edit("delete"))],
            [("Set SEGNO",lambda:a.track_edit("segno")),("Set D.C. (end)",lambda:a.track_edit("dc")),
             ("D.S. at end of bar",lambda:self._jump())],
            [("TRACK PLAY / STOP",a.track_play),("Export track to WAV...",a.export_track)]]:
            r=ttk.Frame(self.t); r.pack(fill="x",pady=(3,0)); self._buttons(r,cmds)
        self.transport_info=ttk.Label(self.t,text="",wraplength=580)
        self.transport_info.pack(anchor="w",pady=3)

    def _jump(self):
        if self.a._track_player: self.a._track_player.request("ds")

    def _choose_track(self):
        a=self.a
        if a._track_player: a._stop()
        a.track_no=int(self.track.get())-1; a.bar_pos=0; a.face_track=True; a._controls_refresh()

    def _bar(self,event):
        sel=self.rows.curselection()
        if not sel: return
        self.a.bar_pos=sel[0]
        bars=self.a.tracks[self.a.track_no].bars
        if sel[0]<len(bars):
            self.shift.set(str(bars[sel[0]][1]))
        if hasattr(self.a,"_face"): self.a._face.sync()

    def show(self,tab):
        self.a.face_track=(tab==1)
        self.book.select(tab); self.deiconify(); self.lift(); self.a._controls_refresh()

    def live(self):
        player=self.a._track_player
        if player is None:
            msg="Playback ends at D.C. Changes to the track take effect the next time you start playback."
        elif getattr(player,"waiting",False):
            msg="MIDI Clock armed. Waiting for START or CONTINUE and incoming clock pulses."
        elif getattr(player,"started",True) is None:
            msg=f"Preparing audio: {player.progress}/{len(player.score.bars)} bars."
        else:
            msg=f"Playing bar {player.index+1} · pattern {label(player.score.track.bars[player.index][0])}"
        self.transport_info.configure(text=msg)

    def sync(self):
        a=self.a; p=a._pat(); b=a._selector_slot()
        if self.winfo_viewable():
            target=1 if a.face_track else 0
            if self.book.index("current")!=target: self.book.select(target)
        self.group.set(str(1+b//16)); self.section.set("AB"[(b//8)%2]); self.slot.set(str(1+b%8))
        self.mode.set(a.editor); self.length.set(str(p.length)); self.prof.set(a.profile.title())
        self.clock.set(a.scale_v.get()); self.track.set(str(1+a.track_no))
        text={"Grid":"Grid: the keyboard writes to the selected step.",
              "Pitch":"Pitch: enter notes in order on the keyboard. Switch to Time to set their rhythm.",
              "Time":"Time: Note uses the next pitch, Tie holds the previous note, and a dot marks a rest."}[a.editor]
        if a._tap_times is not None: text=f"Tap armed · {len(a._tap_times)} taps. The first tap sets the start."
        self.keys.configure(text=text)
        names=[(n["note"] or "·")+("+" if n["accent"] else "")+("~" if n["slide"] else "") for n in p.pitches]
        self.pitch_line.configure(text=f"Pitches · cursor {a.pc+1:02}: "+("  ".join(names) or "none"))
        cells=p.grid()
        for i,btn in enumerate(self.cells):
            s=cells[i]
            txt="TIE" if s.get("tie") else s["note"] or ("?" if s.get("on") else ".")
            btn.configure(text=f"{i+1:02} {txt}")
            btn.state(["disabled" if i>=p.length else "!disabled","pressed" if i==a.sel else "!pressed"])
        t=a.tracks[a.track_no]
        rows=tuple(f"{i+1:02}    {label(slot)}    {shift:+d} semitones"+
             ("    SEGNO" if t.segno==i else "")+("    D.C." if t.dc==i else "") for i,(slot,shift) in enumerate(t.bars))
        if len(t.bars)<64: rows+=("+   Add a bar",)
        pos=min(a.bar_pos,len(rows)-1)
        if self._last_rows!=rows:
            self.rows.delete(0,"end")
            for s in rows: self.rows.insert("end",s)
            self._last_rows=rows
        if self.rows.curselection()!=(pos,):
            self.rows.selection_clear(0,"end"); self.rows.selection_set(pos); self.rows.see(pos)
        self.live()
        self.detail.configure(text=getattr(a,"last_action","PREV/NEXT moves the cursor. BACK undoes an edit. REDO restores it."))

