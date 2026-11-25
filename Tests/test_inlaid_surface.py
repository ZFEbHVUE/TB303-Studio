"""Registration, live gestures, keyboard selectors and alternate artwork."""
import sys
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image, ImageChops
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"Python_Scripts"))
import tb303_studio as studio
from build_face_skins import source_path, state_box
from face_layout import SKIN_NAMES, KEYS, SEAM, UPPER, BAY, HEIGHT, WIDTH
from sequencer_face import compose

class RegistrationTests(unittest.TestCase):
    def test_original_transport_steps_and_footer_are_registered_in_every_factory_case(self):
        for skin in SKIN_NAMES:
            with self.subTest(skin=skin),Image.open(source_path(skin)) as src:
                source=src.convert("RGB"); surface,switches=compose(source,skin)
                self.assertEqual(surface.size,(WIDTH,HEIGHT))
                for x,y,X,Y,shift in ((250,56,838,205,0),(78,398,214,587,0),
                                     (370,571,1553,652,UPPER),(381,711,1290,748,BAY)):
                    original=source.crop((x,y,X,Y))
                    actual=surface.crop((x,y+shift,X,Y+shift))
                    self.assertIsNone(ImageChops.difference(original,actual).getbbox())
                for key in KEYS.values():
                    x,y,X,Y=key.box
                    rest=surface.crop((x,y+SEAM,X,Y+SEAM))
                    lit=switches.crop(state_box(key,1));down=switches.crop(state_box(key,2))
                    self.assertIsNotNone(ImageChops.difference(rest,lit).getbbox(),key.id)
                    self.assertIsNotNone(ImageChops.difference(lit,down).getbbox(),key.id)

    def test_custom_case_uses_its_supplied_fittings(self):
        with Image.open(source_path("steampunk")) as src:
            custom=src.convert("RGB")
        # Refinish the original transport button without touching the new switch row.
        from PIL import ImageOps
        box=(63,494,233,600)
        custom.paste(ImageOps.colorize(ImageOps.grayscale(custom.crop(box)),"#170934","#e1c8ff"),box[:2])
        made,_=compose(custom,"custom")
        stock,_=compose(Image.open(source_path("steampunk")).convert("RGB"),"steampunk")
        x,y,X,Y=KEYS["back"].box
        area=(x+8,y+SEAM+8,X-8,Y+SEAM-8)
        self.assertIsNotNone(ImageChops.difference(made.crop(area),stock.crop(area)).getbbox())
        self.assertEqual(custom.getpixel((130,445)),made.getpixel((130,445)))

class LiveSurfaceTests(unittest.TestCase):
    def setUp(self):
        try:self.root=tk.Tk()
        except tk.TclError as exc:self.skipTest(str(exc))
        self.root.winfo_screenwidth=lambda:1280
        self.root.winfo_screenheight=lambda:720
        with patch.object(studio,"_HAS_RT",False),patch.object(studio,"_HAS_PYGAME",False):
            self.app=studio.SkinStudio(self.root,studio._find_skin())
        self.root.update()
    def tearDown(self):
        if hasattr(self,"app"):self.app.close();self.root.destroy()
    def click(self,x,y):
        a=self.app
        for e in ("<ButtonPress-1>","<ButtonRelease-1>"):
            a.cv.event_generate(e,x=round(a.S(x)),y=round(a.S(y)));self.root.update()
    def test_all_original_steps_and_open_chassis_pass_through_the_sequencer(self):
        a=self.app
        for skin in ("steampunk","classic"):
            a.skin_v.set(skin);a._change_skin();self.root.update()
            for i,x in enumerate(a.M["cells"]["cx"]):
                self.click(x,a.M["cells"]["cy"]);self.assertEqual(a.sel,i)
            for x,y in ((553,SEAM+39),(1108,SEAM+185),(747,SEAM+261)):
                event=SimpleNamespace(x=round(a.S(x)),y=round(a.S(y)))
                self.assertFalse(a._face.press(event));self.assertFalse(a._face.captured)
                self.click(x,y);self.assertEqual(a.sel,15)
    def pointer(self,widget,x=None,y=None):
        x=widget.winfo_width()//2 if x is None else x
        y=widget.winfo_height()//2 if y is None else y
        for e in ("<ButtonPress-1>","<ButtonRelease-1>"):
            widget.event_generate(e,x=x,y=y);self.root.update()

    def key(self,widget,key):
        widget.event_generate("<"+key+">");self.root.update()

    def pick(self,widget,i):
        p=widget.popup
        self.pointer(p,p.winfo_width()//2,widget.margin+i*widget.row+widget.row//2)

    def pixels(self,widget):
        from PIL import ImageTk
        return ImageTk.getimage(widget.photos[widget.variable.get(),widget.keyboard,widget.popup is not None])

    def test_native_selector_opens_and_preserves_keyboard_edits_undo_and_skin_switch(self):
        a=self.app;widget=a._combos["playmode"][0];first=widget.variable.get()
        self.root.focus_force();self.root.update()
        self.pointer(widget);self.assertTrue(widget.popup.winfo_ismapped())
        self.pick(widget,1)
        self.assertIsNone(widget.popup);self.assertEqual(widget.variable.get(),widget.values[1])
        self.assertFalse(widget.keyboard)
        a.history_move(False);self.assertEqual(widget.variable.get(),first)
        a.skin_v.set("classic");a._change_skin();self.root.update()
        widget.focus_force();self.root.update();self.key(widget,"Right")
        self.assertEqual(widget.variable.get(),widget.values[1]);self.assertTrue(widget.keyboard)
        self.key(widget,"Left");self.assertEqual(widget.variable.get(),first)

    def test_mouse_selection_returns_the_exact_unfocused_field_without_an_underline(self):
        a=self.app;w=a._combos["scale"][0];self.root.focus_force();self.root.update()
        before=self.pixels(w);i=w.values.index(w.variable.get());history=len(a.hist.past)
        self.pointer(w);self.pick(w,i)
        self.assertEqual(before.tobytes(),self.pixels(w).tobytes());self.assertFalse(w.keyboard)
        self.assertEqual(len(a.hist.past),history)
        self.pointer(w);self.pick(w,0);self.assertFalse(w.keyboard)
        self.assertNotEqual(before.tobytes(),self.pixels(w).tobytes())
        a.history_move(False);self.assertEqual(before.tobytes(),self.pixels(w).tobytes())

    def test_hover_arrows_escape_and_tab_do_not_commit_until_confirmed(self):
        a=self.app;w=a._combos["scale"][0];old=w.variable.get()
        w.focus_force();self.root.update()
        self.key(w,"Down");self.assertIsNotNone(w.popup);self.assertTrue(w.keyboard)
        self.key(w,"Home");self.assertEqual(w.active,0);self.assertEqual(w.variable.get(),old)
        self.key(w,"Down");self.assertEqual(w.active,1)
        self.key(w,"Escape");self.assertIsNone(w.popup);self.assertEqual(w.variable.get(),old)
        self.key(w,"space");self.key(w,"End");self.key(w,"Return")
        self.assertEqual(w.variable.get(),w.values[-1])
        self.key(w,"Down");self.key(w,"Home");self.key(w,"Tab")
        neighbor=a._combos["playmode"][0]
        self.assertIsNone(w.popup);self.assertEqual(w.variable.get(),w.values[-1])
        self.assertIs(self.root.focus_get(),neighbor);self.assertTrue(neighbor.keyboard)
        self.key(neighbor,"ISO_Left_Tab");self.assertIs(self.root.focus_get(),w)

    def test_click_away_never_sounds_a_note_and_only_one_drawer_can_open(self):
        a=self.app;s=a._combos["scale"][0];p=a._combos["preset"][0]
        self.root.focus_force();self.root.update()
        self.pointer(s);self.pointer(p)
        self.assertIsNone(s.popup);self.assertIsNotNone(p.popup)
        self.assertIsNone(self.root.grab_current())
        with patch.object(a,"_piano_hit") as play:
            self.click(900,500);self.assertIsNone(p.popup);play.assert_not_called()
            self.click(900,500);play.assert_called_once()
        self.pointer(p);self.pointer(p);self.assertIsNone(p.popup)
        self.pointer(s);a.skin_v.set("classic");a._change_skin();self.root.update()
        self.assertIsNone(s.popup);self.assertIsNone(a._active_selector)

    def test_each_skin_posts_all_three_fields_inside_the_canvas_at_laptop_scale(self):
        from build_face_skins import legend_family
        a=self.app;self.root.winfo_screenwidth=lambda:1024;self.root.winfo_screenheight=lambda:600
        for skin in (*SKIN_NAMES[1:],SKIN_NAMES[0]):
            a.skin_v.set(skin);a._change_skin();self.root.update()
            for w,item in a._combos.values():
                with self.subTest(skin=skin,items=w.values):
                    self.pointer(w);p=w.popup
                    self.assertTrue(p.winfo_ismapped());self.assertIs(p.master,a.cv)
                    self.assertEqual(w.lettering.family,legend_family(skin))
                    self.assertLessEqual(p.winfo_y()+p.winfo_height(),a.cv.winfo_height())
                    self.assertLessEqual(p.winfo_x()+p.winfo_width(),a.cv.winfo_width())
                    i=w.active
                    j=(i+1)%len(w.values)
                    p.event_generate("<Motion>",x=p.winfo_width()//2,y=w.margin+j*w.row+w.row//2)
                    self.root.update()
                    self.assertEqual((w.active,w.variable.get()),(j,w.values[i]))
                    self.pick(w,j)
                    self.assertEqual(w.variable.get(),w.values[j]);self.assertFalse(w.keyboard)
