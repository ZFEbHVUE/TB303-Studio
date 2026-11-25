"""Optional photographic front panel. The Studio, its audio device and its project stay alive."""
import math
import time
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
from roland_geometry import SIZE, PHOTO, ROTORS, KEYS, LEDS, DETENTS, BINDINGS, hit, detent_angle, angle
from roland_art import PhotoParts, TileCache
from roland_controls import PanelControls
from roland_transport import read_transport

RESAMPLE=Image.Resampling.LANCZOS if hasattr(Image,"Resampling") else Image.LANCZOS
GUIDE="""The photograph is the control surface. Use the eight round knobs, two rotary selectors and the actual key caps. Drag a knob up or down, turn its rim, or use the mouse wheel. Click a dot around TRACK / PATT. GROUP or MODE to select an exact position. Turning MODE stops the current transport. Switching the view in the Panel menu keeps playback running.

PATTERN PLAY: choose group I–IV with the left selector, section A/B with ACCENT/SLIDE, then pattern 1–8. RUN/STOP starts or stops the engine. During playback a new selection takes effect at the next pattern boundary. Hold two pattern keys in the same block of four to loop the range. Hold PITCH MODE and a keyboard note to transpose playback.

PATTERN WRITE: choose a slot, press PITCH MODE and enter notes. Hold TRANSPOSE, ACCENT or SLIDE as you enter a note. Hold WRITE/NEXT to hear a stored note and see its indicators; BACK goes back one entry for correction. FUNCTION returns to normal. TIME MODE takes NOTE, TIE or REST on the first three keys to its right (9, 0, 100). Hold FUNCTION and press 9 repeatedly to set the length, or press 0 for twelve triplet steps. To clear timing, hold the pattern number and press PATTERN CLEAR.

TRACK WRITE: use the left selector for tracks 1–7. Select a pattern and press WRITE/NEXT to store one bar. Hold PITCH MODE and a note to set its transposition. During playback press D.C. or the segno key (BACK) before writing to mark the bar. In stop, FUNCTION with DEL/INS edits the bar list. TRACK PLAY plays the stored sequence; BAR RESET returns to its start, and D.S. requests a jump at the next bar.

Computer keys let one mouse hold two or more physical controls. For a chromatic octave, use Z S X D C V G B H N J M Q (low C to high C). P = PITCH, T = TIME, F or Shift = FUNCTION, [ and ] = DOWN/UP, comma = ACCENT, period = SLIDE. Space = RUN/STOP, Enter = WRITE/NEXT, Backspace = panel BACK, Delete = CLEAR. Ctrl+Z and Ctrl+Y remain Studio Undo and Redo.

The top WAVEFORM legend opens the rear switch. Turn VOLUME fully down and one more notch to switch off; turning it up switches back on. F9 held shows the untouched photograph at the same size. All Studio menus remain available."""
def clamp(v):return max(0.,min(1.,v))

class RolandPanel:
    def __init__(self,a):
        self.a=a;self.root=a.root;self.controls=PanelControls(a)
        with Image.open(PHOTO) as src:self.original=src.convert("RGB")
        self.parts=PhotoParts(self.original)
        self.scale=min(1.,(self.root.winfo_screenwidth()-20)/SIZE[0],(self.root.winfo_screenheight()-98)/SIZE[1])
        w,h=[round(v*self.scale) for v in SIZE]
        self.cv=tk.Canvas(self.root,width=w,height=h,highlightthickness=0,bd=0,takefocus=1,background="#151515")
        self.base=self.photo(self.original,(w,h))
        self.cv.create_image(0,0,image=self.base,anchor="nw")
        self.cache=TileCache(); self.images={}; self.items={}; self.state={}
        for group,parts in (("rotor",self.parts.rotors),("lamp",self.parts.lenses),("key",self.parts.keys)):
            for name,part in parts.items():
                box=part.box if group=="rotor" else part[0]
                self.items[group,name]=self.cv.create_image(*[round(v*self.scale) for v in box[:2]],
                                                    anchor="nw",state="hidden",tags=("moving",))
        self.visible=False;self.job=None;self.raw=False;self.drag=None;self.sources={};self.release_jobs={}
        cv=self.cv
        cv.bind("<ButtonPress-1>",self.press);cv.bind("<ButtonRelease-1>",self.release)
        cv.bind("<B1-Motion>",self.motion);cv.bind("<Motion>",self.hover)
        for seq in ("<MouseWheel>","<Button-4>","<Button-5>"):cv.bind(seq,self.wheel)
        cv.bind("<KeyPress>",self.keydown);cv.bind("<KeyRelease>",self.keyup)
        cv.bind("<FocusOut>",self.cancel_inputs);cv.bind("<Destroy>",self.destroy)
        self.guide=None

    def photo(self,image,size):
        if image.size!=size:image=image.resize(size,RESAMPLE)
        return ImageTk.PhotoImage(image,master=self.root)

    def show(self):
        if self.visible:return
        self.visible=True;self.controls.show()
        self.a.cv.pack_forget();self.cv.pack();self.cv.focus_set();self.tick()

    def hide(self):
        if not self.visible:return
        self.visible=False
        if self.job is not None:self.root.after_cancel(self.job);self.job=None
        self.cancel_inputs();self.cv.pack_forget();self.a.cv.pack();self.a.cv.focus_set()

    def destroy(self,e):
        if e.widget is self.cv:
            self.visible=False
            if self.job is not None:self.root.after_cancel(self.job);self.job=None
            self.cancel_inputs()

    def cancel_inputs(self,event=None):
        for job in self.release_jobs.values():self.root.after_cancel(job)
        self.release_jobs.clear();self.sources.clear();self.controls.reset_holds()
        if self.drag:self.drag=None;self.a._finish_gesture()
        self.raw=False

    def fraction(self,name):
        val=self.a.kv[name]
        if name=="bpm":return clamp((val-40.)/260.)
        if name=="tuning":return clamp(.5+12.*math.log2(max(1.,val)/440.)/14.)
        return clamp(val)

    def set_fraction(self,name,f,delta=0.):
        c=self.controls
        if name=="volume":
            if not c.power and (delta>0 or f>0):
                c.power_set(True);self.a.photo_power.set(True)
            elif c.power and self.fraction("volume")==0 and delta<0 and f<=0:
                c.power_set(False);self.a.photo_power.set(False)
        if not c.power:return
        f=clamp(f)
        value=40+260*f if name=="bpm" else (440*2**((f-.5)*14/12) if name=="tuning" else f)
        self.a.kv[name]=value;self.a._knob_live(name)

    def rotor_angle(self,name):
        if name in DETENTS:return detent_angle(name,getattr(self.controls,name))
        arc=146 if name in ("bpm","volume") else 129
        return (self.fraction(name)*2-1)*arc

    def update_item(self,group,name,token,box,make):
        k=(group,name)
        if self.state.get(k)==token:return
        self.state[k]=token;item=self.items[k]
        if token is None:
            self.cv.itemconfigure(item,state="hidden");self.images.pop(k,None);return
        size=(round(box[2]*self.scale)-round(box[0]*self.scale),round(box[3]*self.scale)-round(box[1]*self.scale))
        img=self.cache.get_or_create((k,token),lambda:self.photo(make(),size))
        self.images[k]=img;self.cv.itemconfigure(item,image=img,state="normal")

    def draw(self):
        if not self.visible:return
        raw=self.raw or self.a.photo_raw.get()
        t=read_transport(self.a,time.monotonic(),self.controls.epoch)
        lit=self.controls.lamp_ids(t); self.last_lamps=lit
        for name,r in self.parts.rotors.items():
            deg=round(self.rotor_angle(name),1)
            self.update_item("rotor",name,None if raw else deg,r.box,lambda r=r,d=deg:r.frame(d))
        for group,parts,on in (("key",self.parts.keys,self.controls.held),("lamp",self.parts.lenses,lit)):
            for name,(box,p) in parts.items():
                self.update_item(group,name,True if not raw and name in on else None,box,lambda p=p:p)

    def tick(self):
        self.job=None
        if not self.visible:return
        self.draw();self.job=self.root.after(25 if self.a.playing else 50,self.tick)

    def xy(self,e):return e.x/self.scale,e.y/self.scale

    def set_detent(self,n,index):
        index=max(0,min(len(DETENTS[n])-1,int(index)))
        (self.controls.set_mode if n=="mode" else self.controls.set_group)(index)

    def hold(self,source,key):
        if source in self.sources:return
        if key not in self.sources.values():self.controls.press(key)
        self.sources[source]=key;self.draw()

    def unhold(self,source):
        key=self.sources.pop(source,None)
        if key is not None and key not in self.sources.values():self.controls.release(key)
        self.draw()

    def press(self,e):
        self.cv.focus_set()
        if self.a.photo_raw.get() or self.raw:return "break"
        x,y=self.xy(e);kind,n=hit(x,y)
        if kind=="power":
            self.controls.power_set(not self.controls.power);self.a.photo_power.set(self.controls.power)
        elif kind=="rear":self.a.photo_wave.tk_popup(e.x_root,e.y_root)
        elif kind=="key":self.hold("mouse",n)
        elif kind=="mark":self.set_detent(*n)
        elif kind=="rotor":
            r=ROTORS[n];cx,cy=r.base[:2];rad=math.hypot(x-cx,y-cy)
            start=getattr(self.controls,n) if n in DETENTS else self.fraction(n)
            self.drag=(n,x,y,start,rad>.68*r.radius,angle(x,y,cx,cy))
            if n not in DETENTS:self.a._begin_gesture(n)
        self.draw();return "break"

    def release(self,e):
        self.unhold("mouse")
        if self.drag:
            self.drag=None;self.a._finish_gesture()
        return "break"

    def motion(self,e):
        if not self.drag:return
        n,x0,y0,start,rim,a0=self.drag
        x,y=self.xy(e);cx,cy=ROTORS[n].base[:2]
        if n in DETENTS:
            if rim:
                ang=angle(x,y,cx,cy)
                i=min(range(len(DETENTS[n])),key=lambda v:abs((ang-detent_angle(n,v)+180)%360-180))
            else:i=round(start+(y0-y)/18.)
            self.set_detent(n,i)
        else:
            change=((angle(x,y,cx,cy)-a0+180)%360-180)/(292 if n in ("bpm","volume") else 258) if rim else (y0-y)/150.
            self.set_fraction(n,start+change,change)
            if rim:self.drag=(n,x,y,self.fraction(n),True,angle(x,y,cx,cy))
        self.draw();return "break"

    def hover(self,e):
        if not self.drag:
            kind,_=hit(*self.xy(e))
            self.cv.configure(cursor="hand2" if kind else "")

    def wheel(self,e):
        if self.a.photo_raw.get() or self.raw:return "break"
        kind,n=hit(*self.xy(e))
        if kind!="rotor":return
        d=1 if getattr(e,"num",None)==4 or getattr(e,"delta",0)>0 else -1
        if n in DETENTS:self.set_detent(n,getattr(self.controls,n)+d)
        else:
            self.a._begin_gesture(n,delayed=True);self.set_fraction(n,self.fraction(n)+d/40.,d)
        self.draw();return "break"

    @staticmethod
    def symbol(e):
        key=e.keysym
        if len(key)==1:key=key.lower()
        return {",":"comma",".":"period","<":"comma",">":"period","less":"comma","greater":"period",
                "[":"bracketleft","]":"bracketright","{":"bracketleft","}":"bracketright",
                "braceleft":"bracketleft","braceright":"bracketright"," ":"space"}.get(key,key)

    def keydown(self,e):
        if e.state&0x0c:return
        sym=self.symbol(e);source=("kbd",e.keycode)
        if source in self.release_jobs:self.root.after_cancel(self.release_jobs.pop(source))
        if sym=="F9":
            self.raw=True;self.draw();return "break"
        if sym in BINDINGS:
            if not (self.a.photo_raw.get() or self.raw):self.hold(source,BINDINGS[sym])
            return "break"

    def keyup(self,e):
        sym=self.symbol(e);source=("kbd",e.keycode)
        if sym not in BINDINGS and sym!="F9" and source not in self.sources:return
        if source in self.release_jobs:self.root.after_cancel(self.release_jobs.pop(source))
        def ended():
            self.release_jobs.pop(source,None)
            if sym=="F9":self.raw=False
            self.unhold(source)
        self.release_jobs[source]=self.root.after_idle(ended)
        return "break"

    def show_guide(self):
        if self.guide is not None and self.guide.winfo_exists():
            self.guide.lift();return
        w=self.guide=tk.Toplevel(self.root);w.title("Roland TB-303 — Operating guide")
        frame=ttk.Frame(w,padding=12);frame.pack(fill="both",expand=True)
        sb=ttk.Scrollbar(frame);sb.pack(side="right",fill="y")
        tx=tk.Text(frame,width=79,height=24,wrap="word",padx=8,pady=8,yscrollcommand=sb.set)
        tx.insert("1.0",GUIDE);tx.config(state="disabled");tx.pack(fill="both",expand=True);sb.config(command=tx.yview)
        ttk.Button(w,text="Close",command=w.destroy).pack(pady=(0,8))

def install(a,menubar):
    a.panel_v=tk.StringVar(a.root,"studio")
    a.photo_raw=tk.BooleanVar(a.root,False);a.photo_power=tk.BooleanVar(a.root,True)
    a.photo_wave_v=tk.StringVar(a.root,a.waveform)
    menu=tk.Menu(menubar,tearoff=0)
    for value,label in (("studio","Studio skins"),("roland","Roland TB-303 (photo)")):
        menu.add_radiobutton(label=label,variable=a.panel_v,value=value,command=lambda:a.show_panel(a.panel_v.get()))
    menu.add_separator()
    wave=a.photo_wave=tk.Menu(menu,tearoff=0,postcommand=lambda:a.photo_wave_v.set(a.waveform))
    def set_wave():
        with a._editing("Waveform"):
            a.waveform=a.photo_wave_v.get();a._track_parameter("waveform",a.waveform);a._changed()
    for value,label in (("saw","Sawtooth"),("square","Square")):
        wave.add_radiobutton(label=label,variable=a.photo_wave_v,value=value,command=set_wave)
    menu.add_cascade(label="Rear waveform switch",menu=wave)
    def power():
        a.show_panel("roland");a._roland_view.controls.power_set(a.photo_power.get());a._roland_view.draw()
    def compare():
        a.show_panel("roland");a._roland_view.draw()
    def guide():
        a.show_panel("roland");a._roland_view.show_guide()
    menu.add_checkbutton(label="Photo panel power",variable=a.photo_power,command=power)
    menu.add_checkbutton(label="Reference photo only",accelerator="Hold F9",variable=a.photo_raw,command=compare)
    menu.add_command(label="Operating guide...",command=guide)
    menubar.add_cascade(label="Panel",menu=menu)
