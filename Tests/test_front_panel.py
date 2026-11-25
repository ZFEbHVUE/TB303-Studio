"""End-to-end Tk tests: send pointer events to the displayed instrument, not its handlers."""
import sys
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"Python_Scripts"))
import tb303_studio as studio
from face_layout import SEAM, BAY, KEYS, bay_x

class FaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try: cls.root=tk.Tk()
        except tk.TclError as exc: raise unittest.SkipTest(f"Tk display unavailable: {exc}")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls): cls.root.destroy()

    def setUp(self):
        self.errors=[]
        # A test failure should surface in CI instead of blocking in a modal dialog.
        dialogs=patch("studio_messages.showerror",side_effect=lambda title,msg,**kw:self.fail(f"{title}: {msg}"))
        dialogs.start(); self.addCleanup(dialogs.stop)
        self.root.report_callback_exception=lambda kind,exc,tb:self.errors.append(exc)
        self.w=tk.Toplevel(self.root)
        # Laptop-size screen; the UI really renders at this scale, not just its hit logic.
        self.w.winfo_screenwidth=lambda:1280
        self.w.winfo_screenheight=lambda:720
        self.w.geometry("+0+0")
        with patch.object(studio,"_HAS_RT",False),patch.object(studio,"_HAS_PYGAME",False):
            self.a=studio.SkinStudio(self.w,studio._find_skin())
        self.w.update()
        self.plate=self.a._face

    def tearDown(self):
        self.a.close()
        if self.a._classic_win is not None:self.a._classic_win.destroy()
        self.w.destroy()
        self.assertEqual(self.errors,[])

    def xy(self,key):
        l,t,r,b=KEYS[key].box
        return (round(self.a.S(bay_x((l+r)/2))),round(self.a.S(SEAM+(t+b)/2)))

    def event(self,name,xy):
        self.a.cv.event_generate(name,x=xy[0],y=xy[1])
        self.w.update()

    def tapxy(self,x,y):
        self.event("<ButtonPress-1>",(x,y));self.event("<ButtonRelease-1>",(x,y))

    def key(self,k): self.tapxy(*self.xy(k))

    def native(self,x,y): self.tapxy(round(self.a.S(x)),round(self.a.S(y)))

    def test_keyboard_edit_navigation_back_redo_and_lamps(self):
        a=self.a; old=a.steps[0].copy()
        self.assertIsNone(a._classic_win)
        self.assertTrue("Mk III" in self.w.title())
        self.assertEqual(self.plate.states["back"],0)
        # E, a white key, near the lower edge of the original graphic.
        self.native(347,530)
        changed=a.steps[0].copy(); self.assertNotEqual(changed,old)
        self.assertEqual(self.plate.states["back"],1)
        self.key("next");self.key("next");self.key("prev")
        self.assertEqual(len(a.hist.past),1)
        self.key("back");self.assertEqual((a.sel,a.steps[0]),(0,old))
        self.assertEqual((self.plate.states["back"],self.plate.states["redo"]),(0,1))
        self.key("redo");self.assertEqual(a.steps[0],changed)
        self.assertIn("STEP",a.cv.itemcget(self.plate.lines[0],"text"))

    def test_mouse_and_midi_waveform_edits_use_the_same_undo_label(self):
        import midi_in
        app = self.a
        previous = app.waveform
        target = "saw" if previous == "square" else "square"
        self.native(*app.M["waveform"][target])
        self.assertEqual(app.waveform, target)
        self.key("back")
        self.assertEqual((app.waveform, app.last_action), (previous, "Undone: Waveform"))
        bridge = object.__new__(midi_in.MidiBridge)
        bridge.app, bridge.verbose = app, False
        with patch.object(bridge, "_draw_badge"):
            bridge._action("wave_" + target)
        self.key("back")
        self.assertEqual((app.waveform, app.last_action), (previous, "Undone: Waveform"))
        self.key("redo")
        self.assertEqual((app.waveform, app.last_action), (target, "Redone: Waveform"))

    def test_timing_length_original_footer_and_cancelled_drag(self):
        a=self.a; self.key("pitch"); self.key("time")
        self.assertEqual((a.editor,self.plate.states["time"]),("Time",1))
        self.key("note");self.key("tie");self.key("rest")
        self.assertEqual(a._pat().time[:3],list("NTR"))
        self.key("shorter");self.assertEqual(a._pat().length,15)
        self.key("pitch");self.key("prev");self.assertIn("PITCH 16/16",self.plate.texts[0])
        self.key("time");self.key("longer");self.assertEqual(a._pat().length,16)
        self.key("reset");self.assertEqual(a.sel,0)
        self.key("next"); self.key("next");self.key("grid");self.key("next")
        self.key("tie");self.assertEqual((a.sel,a._pat().time[1]),(2,"T"))
        count=len(a.hist.past);xy=self.xy("del")
        self.event("<ButtonPress-1>",xy);self.assertEqual(self.plate.states["del"],2)
        self.event("<B1-Motion>",self.xy("ins"));self.event("<ButtonRelease-1>",self.xy("ins"))
        self.assertEqual(len(a.hist.past),count); self.assertNotEqual(self.plate.states["del"],2)
        self.native(629,729+BAY);self.assertFalse(any(e["note"] for e in a.steps))
        self.native(783,728+BAY);self.assertTrue(any(e["note"] for e in a.steps))
        with patch.object(a,"_toggle_record") as record:
            self.native(455,728+BAY);record.assert_called_once()
        self.assertIsNone(a._classic_win)

    def test_build_track_and_readout_from_face_only(self):
        a=self.a
        self.key("track_play");self.assertIn("EMPTY",self.plate.texts[1])
        self.key("group");self.key("section")
        bankx=a.M["banks"][3];self.native(bankx,a.M["banks_y"])
        self.assertEqual(a.cur_bank,27)
        self.key("track_write");self.key("write");self.assertEqual(a.tracks[0].bars,[(27,0)])
        self.key("section");self.key("write");self.assertEqual(a.tracks[0].bars,[(27,0),(19,0)])
        self.key("bar_prev");self.key("ins");self.assertEqual(len(a.tracks[0].bars),3)
        self.key("del");self.assertEqual(a.tracks[0].bars,[(27,0),(19,0)])
        self.key("back");self.assertEqual(len(a.tracks[0].bars),3)
        self.key("redo");self.assertEqual(len(a.tracks[0].bars),2)
        self.assertTrue(a.face_track)
        pos=a.bar_pos;self.key("prev");self.assertEqual(a.bar_pos,pos)
        self.key("bar_next");self.assertEqual(a.bar_pos,2)
        self.key("reset");self.assertEqual(a.bar_pos,0)
        # Prove the control actually starts/stops the real transport; only the device
        # is replaced. Playback rendering itself has regression coverage in test_classic.
        import threading
        host=SimpleNamespace(stream=SimpleNamespace(active=True),_lock=threading.Lock(),track_source=None,get_level=lambda:0.)
        with patch.object(a,"_active_engine",return_value=host):
            self.key("track_play");self.assertIsNotNone(host.track_source)
            self.assertEqual(self.plate.states["track_play"],1)
            self.key("track_play");self.assertIsNone(host.track_source)
        self.key("track");self.assertEqual(a.track_no,1)
        self.key("time");self.assertFalse(a.face_track);self.assertIsNone(a._classic_win)

    def test_all_skins_keep_art_hit_targets_and_screen_inside_at_two_sizes(self):
        a=self.a; self.assertEqual(len(a._skins),11)
        for i,key in enumerate(a._skins):
            for width,height in ((1280,720),(1024,600)) if i==1 else ((1280,720),):
                with self.subTest(skin=key,size=(width,height)):
                    # Remount even if it is the initial skin to exercise a changed resolution.
                    self.w.winfo_screenwidth=lambda:width;self.w.winfo_screenheight=lambda:height
                    if key==a._skin:
                        other="classic" if key!="classic" else "steampunk"
                        a.skin_v.set(other);a._change_skin()
                    a.skin_v.set(key);a._change_skin();self.w.update()
                    a.mode_select("Grid")
                    self.key("time");self.assertEqual(a.editor,"Time")
                    self.key("grid");self.key("next");self.assertEqual(a.sel,1)
                    self.assertEqual(self.plate.states["grid"],1)
                    self.assertLessEqual(a.cv.winfo_height()+55,height)
                    self.assertLessEqual(a.cv.winfo_width(),width)
                    # Each pixel used as a centre hit lives inside the painted face.
                    xy=[self.xy(k) for k in KEYS]
                    self.assertEqual(len(xy),len(set(xy)))
                    for k,(x,y) in zip(KEYS,xy):
                        self.assertEqual(self.plate.position(SimpleNamespace(x=x,y=y)),k)
                    self.assertLess(a.cv.coords(self.plate.lines[0])[1],a.cv.winfo_height())
                    self.assertLessEqual(len(a.cv.find_withtag("inlay")),len(KEYS)+2)

    def test_companion_and_front_face_share_editor_and_bank(self):
        a=self.a;a.show_classic(1);self.w.update()
        self.assertTrue(a.face_track)
        a._classic_win.book.select(0);self.w.update()
        self.assertFalse(a.face_track)
        self.key("group");self.key("section")
        self.assertEqual((a._classic_win.group.get(),a._classic_win.section.get()),("2","B"))
        self.key("track_write");self.assertEqual(a._classic_win.book.index("current"),1)
        self.key("pitch");self.assertEqual(a._classic_win.book.index("current"),0)
        self.assertEqual(a._classic_win.mode.get(),"Pitch")
        a.show_classic(1);self.w.update()
        a._classic_win.track.set("6");a._classic_win._choose_track()
        self.assertEqual(a.track_no,5);self.assertIn("T6",self.plate.texts[1])

