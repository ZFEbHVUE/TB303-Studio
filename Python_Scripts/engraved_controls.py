"""Value windows and dial indices made from the instrument's own artwork."""
import math
import tkinter as tk
from PIL import ImageTk
from selector_art import Lettering, DrawerArt, field_picture

class SkinSelector(tk.Canvas):
    """A field and an in-panel drawer. Only an explicit choice edits the synth."""
    def __init__(self, parent, variable, values, changed):
        super().__init__(parent,highlightthickness=0,borderwidth=0,takefocus=1,
                         width=1,height=1,cursor="hand2")
        self.variable=variable;self.values=tuple(values);self.changed=changed
        self.app=self.popup=self.patch=None
        self.face_item=self.create_image(0,0,anchor="nw")
        self.keyboard=False;self.pointer_focus=False
        self.photos={};self.active=-1
        self.trace=variable.trace_add("write",self.update_value)
        self.bind("<Destroy>",self._destroyed)
        self.bind("<Unmap>",lambda e:self.dismiss())
        self.bind("<ButtonPress-1>",self._field_press)
        self.bind("<ButtonRelease-1>",self._field_release)
        self.bind("<B1-Motion>",self._field_drag)
        self.bind("<FocusIn>",self._focus_in);self.bind("<FocusOut>",self._focus_out)
        for sequence in ("<space>","<Return>","<KP_Enter>","<Alt-Down>"):
            self.bind(sequence,self._open_or_commit)
        for key,delta in (("Down",1),("Up",-1),("Right",1),("Left",-1)):
            self.bind("<"+key+">",lambda e,k=key,n=delta:self._arrow(k,n))
        for key,end in (("Home",0),("End",len(self.values)-1)):
            self.bind("<"+key+">",lambda e,i=end:self._edge(i))
        self.bind("<Escape>",self._cancel)
        for key in ("<Tab>","<Shift-Tab>","<ISO_Left_Tab>"):
            self.bind(key,self._tab)

    def fit(self,app,x,y,width):
        self.dismiss()
        self.app=app
        S=app.S
        l,t,r,b=round(S(x-width/2)),round(S(y-13)),round(S(x+width/2)),round(S(y+13))
        self.anchor_x=l;self.anchor_y=t
        self.configure(width=r-l,height=b-t)
        self.patch=app._disp_rgb.crop((l,t,r,b))
        self.lettering=Lettering(app._skin,app.scale)
        self.material=app.img.crop((round(x-width*.34),round(y-8),round(x+width*.17),round(y+8)))
        self.photos.clear();self._draw_field()
        return l,t

    def _destroyed(self,e):
        if e.widget is self:
            self.close()
            self.variable.trace_remove("write",self.trace)

    def close(self):
        self.dismiss()
        self.photos.clear()

    def _draw_field(self):
        if self.patch is None:return
        key=(self.variable.get(),self.keyboard,self.popup is not None)
        if key not in self.photos:
            pic=field_picture(self.patch,self.lettering,*key)
            self.photos[key]=ImageTk.PhotoImage(pic,master=self)
        self.itemconfigure(self.face_item,image=self.photos[key])

    def update_value(self,*_):
        self._draw_field()
        if self.popup is not None:self._paint_list()

    def _draw_focus(self,keyboard):
        self.keyboard=keyboard;self._draw_field()

    def _focus_in(self,_):
        self._draw_focus(not self.pointer_focus)

    def _focus_out(self,_):
        self.keyboard=False;self.pointer_focus=False;self.dismiss();self._draw_field()

    def _index(self):
        try:return self.values.index(self.variable.get())
        except ValueError:return -1

    def _list_index(self,root_x,root_y):
        p=self.popup
        if p is None:return None
        x=root_x-p.winfo_rootx();y=root_y-p.winfo_rooty()-self.margin
        if not self.margin//2<=x<p.winfo_width()-self.margin//2 or y<0:return None
        i=int(y//self.row)
        return i if i<len(self.values) else None

    def _set_active(self,i):
        if i is not None and self.popup is not None and i!=self.active:
            self.active=i;self._paint_list()

    def _paint_list(self):
        key=(self._index(),self.active)
        if key not in self.row_photos:
            img=self.drawer.picture(*key)
            self.row_photos[key]=ImageTk.PhotoImage(img,master=self.popup)
        self.popup.itemconfigure(self.rows_item,image=self.row_photos[key])

    def open(self,keyboard):
        a=self.app
        if self.popup is not None:return
        if a._active_selector is not None:a._active_selector.dismiss()
        self.pointer_focus=not keyboard;self._draw_focus(keyboard)
        self.focus_set()
        a._active_selector=self
        # A placed canvas keeps the list on the instrument and follows the
        # window. It does not open another system window or take a global grab.
        W,H=a._disp_rgb.size
        self.row=max(18,round(31*a.scale),self.lettering.size+6)
        self.margin=max(4,round(7*a.scale))
        wide=max(self.patch.width,round(max(self.lettering.width(v) for v in self.values)
                        +max(24,35*a.scale)))
        wide=min(wide,W);high=2*self.margin+self.row*len(self.values)
        x=min(max(0,self.anchor_x),W-wide)
        below=self.anchor_y+self.patch.height+max(1,round(2*a.scale))
        y=below if below+high<=H else max(0,self.anchor_y-high-1)
        background=a._disp_rgb.crop((x,y,x+wide,y+high))
        self.drawer=DrawerArt(background,self.material,self.lettering,self.row,self.margin,self.values)
        self.row_photos={};self.active=max(0,self._index())
        p=self.popup=tk.Canvas(self.master,highlightthickness=0,borderwidth=0,takefocus=0,
                               width=wide,height=high,cursor="hand2",background="#211d17")
        self.rows_item=p.create_image(0,0,anchor="nw")
        self._paint_list();p.place(x=x,y=y,width=wide,height=high)
        tk.Misc.tkraise(p)  # Raise the widget; Canvas.tkraise would raise an item.
        p.bind("<Motion>",self._hover);p.bind("<B1-Motion>",self._hover)
        p.bind("<ButtonPress-1>",self._hover);p.bind("<ButtonRelease-1>",self._row_release)
        self._draw_field()

    def dismiss(self):
        if self.popup is None:return False
        popup,self.popup=self.popup,None
        if self.app._active_selector is self:self.app._active_selector=None
        if popup.winfo_exists():popup.destroy()
        self.row_photos.clear();self.drawer=None;self.active=-1
        if self.winfo_exists():self._draw_field()
        return True

    def _choose(self,i,keyboard):
        self.pointer_focus=not keyboard;self.keyboard=keyboard
        value=self.values[i];self.dismiss();self._draw_field()
        if value!=self.variable.get():
            self.variable.set(value);self.changed()
        return "break"

    def _field_press(self,_):
        self.pointer_focus=True;self._draw_focus(False)
        if self.popup is None:self.open(False)
        else:self.dismiss()
        return "break"

    def _hover(self,e):
        self._set_active(self._list_index(e.x_root,e.y_root));return "break"

    def _field_drag(self,e):
        return self._hover(e)

    def _field_release(self,e):
        # Opening on button-down also permits a continuous press/drag/release.
        if self.popup is not None:
            i=self._list_index(e.x_root,e.y_root)
            if i is not None:return self._choose(i,False)
            if not (0<=e.x<self.winfo_width() and 0<=e.y<self.winfo_height()):self.dismiss()
        return "break"

    def _row_release(self,e):
        i=self._list_index(e.x_root,e.y_root)
        if i is not None:return self._choose(i,False)
        self.dismiss();return "break"

    def _open_or_commit(self,_):
        if self.popup is None:self.open(True)
        else:return self._choose(self.active,True)
        return "break"

    def _arrow(self,key,delta):
        self.pointer_focus=False;self._draw_focus(True)
        if self.popup is None and key in ("Up","Down"):
            self.open(True)
        elif self.popup is not None:
            self._set_active(max(0,min(len(self.values)-1,self.active+delta)))
        else:
            return self._choose(max(0,min(len(self.values)-1,self._index()+delta)),True)
        return "break"

    def _edge(self,index):
        self.pointer_focus=False;self._draw_focus(True)
        if self.popup is None:return self._choose(index,True)
        self._set_active(index);return "break"

    def _cancel(self,_):
        if self.popup is None:return None
        self.pointer_focus=False;self._draw_focus(True);self.dismiss();return "break"

    def _tab(self,_):
        self.dismiss();self.pointer_focus=False
        # Let Tk move focus normally, including Shift-Tab; the next field lights its index.
        return None


def dial_index(app,x,y,r,angle):
    """A rotating bevelled inlay leaves the native hub and fixed rim visible."""
    S=app.S; v=(math.cos(angle),math.sin(angle)); n=(-v[1],v[0])
    def point(along,across,depth=0):
        return (S(x+v[0]*r*along+n[0]*across+depth),S(y+v[1]*r*along+n[1]*across+depth))
    historic=app._skin in ("steampunk","steampunk_ii","dub","reggae","custom")
    light=app.M["needle"]
    base="#92672f" if historic else ("#962e28" if app._skin=="classic" else "#24525a")
    cv=app.cv; w=2.4 if historic else 2.05
    for off,c in ((1.1,"#211c19"),(0,base)):
        cv.create_polygon(*point(.13,-w,off),*point(.78,-w*.73,off),*point(.88,0,off),
                          *point(.78,w*.73,off),*point(.13,w,off),fill=c,outline="",tags="dyn")
    cv.create_line(*point(.18,-.66),*point(.78,-.58),fill=light,width=max(1.,S(1.8)),tags="dyn")

