"""Regression tests for the original-panel photograph, gestures and audible indicators."""
import sys, math, time, tkinter as tk, unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import numpy as np
from PIL import Image, ImageChops
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"Python_Scripts"))
import tb303_studio as studio
from tb303 import parse_step
from tb303_rt import RealtimeEngine
from classic_sequence import Pattern,Track
from live_pattern import PatternPlayer
from classic_track import Score,Transport
from roland_geometry import KEYS,LEDS,ROTORS,WHITES,PHOTO,DETENTS,hit
from roland_art import PhotoParts
from roland_transport import read_transport,TransportView
from roland_audio import PatternOutput,TrackOutput
from test_pattern_switch import bank,Channel,render

class RegistrationTests(unittest.TestCase):
    def test_only_moving_metal_is_reconstructed(self):
        with Image.open(PHOTO) as source:img=source.convert("RGB")
        self.assertEqual(img.size,(1656,814))
        parts=PhotoParts(img)
        self.assertEqual((len(parts.rotors),len(parts.keys),len(parts.lenses)),(10,24,21))
        for name,r in parts.rotors.items():
            same=r.frame(ROTORS[name].reference);diff=ImageChops.difference(same,r.frame(r.ref-74))
            self.assertIsNone(ImageChops.difference(same,img.crop(r.box)).getbbox(),name)
            self.assertIsNotNone(diff.getbbox(),name)
            self.assertEqual(diff.getpixel((0,0)),(0,0,0))
        for key,(l,t,r,b) in KEYS.items():self.assertEqual(hit((l+r)/2,(t+b)/2),("key",key))
        for name,marks in DETENTS.items():
            for i,xy in enumerate(marks):self.assertEqual(hit(*xy),("mark",(name,i)))
        self.assertNotEqual(hit(*LEDS["time"][:2]),("key","time"))

class PanelAudioTests(unittest.TestCase):
    def test_range_repeats_on_real_boundaries_even_in_one_large_callback(self):
        specs=[bank(i,[n],sr=8000,bpm=120) for i,n in enumerate(("C2","G2","D3"))]
        engine=PatternPlayer(specs[0]);engine.queue_playlist(specs)
        engine.fill(np.empty(7000));self.assertEqual(engine.snapshot()[0].slot,1)
        self.assertAlmostEqual(engine.beat_phase,.75)
        engine.fill(np.empty(999));self.assertEqual(engine.snapshot()[0].slot,1)
        engine.fill(np.empty(1));self.assertEqual(engine.snapshot()[0].slot,2)
        s=bank(2,["D4"],sr=8000,bpm=120);s.transpose=12
        engine.request(s);engine.fill(np.empty(1001))
        self.assertEqual((engine.current.slot,engine.current.transpose),(2,12))
        self.assertIsNone(engine.snapshot()[1])

    def test_replacing_a_chain_waits_until_the_last_measure_finishes(self):
        specs=[bank(i,[n],sr=8000,bpm=120) for i,n in enumerate(("C2","D2","E2","F2"))]
        p=PatternPlayer(specs[0]);p.queue_playlist(specs[:3]);render(p,300)
        p.queue_playlist([specs[3]],finish_series=True)
        for n,want in ((700,1),(1000,2),(999,2),(1,3),(1500,3)):
            render(p,n);self.assertEqual(p.current.slot,want)
        self.assertIsNone(p.target)

    def test_sdl_lamps_follow_output_not_prefetched_audio_and_controls_reach_pcm(self):
        ch=Channel();pg=NS(mixer=NS(find_channel=lambda force:ch),sndarray=NS(make_sound=lambda pcm:NS(pcm=pcm)))
        s0=bank(0,["C2","D2","G2","A2"],sr=8000,bpm=120);s1=bank(1,["F2"],sr=8000,bpm=120)
        p=PatternOutput(s0,pg,False);p.request(s1)
        heard=[]
        for _ in range(7):
            heard.append(ch.consume(512));p.service()
        self.assertEqual(p.player.current.slot,1)
        self.assertEqual(p.snapshot()[0].slot,0)
        for _ in range(2):ch.consume(512);p.service()
        self.assertEqual(p.audible_view().slot,1)
        self.assertGreater(np.max(np.abs(np.concatenate(heard))),0)
        p.knob(1,"volume",0.);out=[]
        for _ in range(5):out.append(ch.consume(512));p.service()
        self.assertFalse(np.any(out[-1]));p.finish()
        t=Track();t.put(0,0);t.put(1,1)
        score=Score(t,lambda i,_:[s0,s1][i].make_bar(),8000)
        tr=TrackOutput(score,pg,start_at=1,background=False);self.assertEqual(tr.audible_view().slot,1)
        tr.knob("bpm",60.);self.assertAlmostEqual(score.bars[0].duration,8000.)
        tr.knob("volume",0.);out=[]
        for _ in range(6):out.append(ch.consume(512));tr.service()
        self.assertFalse(np.any(out[-1]));tr.stop()

class FaceTests(unittest.TestCase):
    def setUp(self):
        try:self.root=tk.Tk()
        except tk.TclError as exc:raise unittest.SkipTest(str(exc))
        self.errors=[];self.root.report_callback_exception=lambda _,exc,tb:self.errors.append(exc)
        self.er=patch("studio_messages.showerror",side_effect=lambda *a,**kw:self.fail(str(a)));self.er.start()
        with patch.object(studio,"_HAS_RT",False),patch.object(studio,"_HAS_PYGAME",False):
            self.a=studio.SkinStudio(self.root,studio._find_skin())
        a=self.a;a.SR=12000;self.host=RealtimeEngine(a.SR)
        self.host.stream=NS(active=True);a.rt=self.host;a.mode="rt";a.audio_ok=True
        self.root.update();a.show_panel("roland");self.root.update()
        self.p=a._roland_view;self.c=self.p.controls
        self.p.cv.focus_force();self.root.update()

    def tearDown(self):
        self.host.stream=None;self.a.close();self.root.destroy();self.er.stop();self.assertEqual(self.errors,[])

    def clickxy(self,x,y,kind=None):
        events=("<ButtonPress-1>","<ButtonRelease-1>") if kind is None else (kind,)
        for e in events:self.p.cv.event_generate(e,x=round(x*self.p.scale),y=round(y*self.p.scale))
        self.root.update_idletasks()

    def key(self,name,kind=None):
        l,t,r,b=KEYS[name];self.clickxy((l+r)/2,(t+b)/2,kind)

    def mark(self,k,i):self.clickxy(*DETENTS[k][i])
    def audio(self,n):
        buf=np.empty((n,2),np.float32);self.host._callback(buf,n,None,None);return buf

    def test_pot_drag_is_one_undo_no_chassis_moves_and_keyboard_reference(self):
        a=self.a;p=self.p;x,y=ROTORS["cutoff"].base[:2]
        start=a.kv["cutoff"];self.clickxy(x,y,"<ButtonPress-1>")
        for dy in (12,24,36):self.clickxy(x,y-dy,"<B1-Motion>")
        self.clickxy(x,y-36,"<ButtonRelease-1>");self.assertAlmostEqual(a.kv["cutoff"],start+.24,places=2)
        a.history_move();self.assertAlmostEqual(a.kv["cutoff"],start)
        p.cv.event_generate("<KeyPress-F9>");self.root.update()
        self.assertTrue(p.raw);self.assertFalse(any(p.cv.itemcget(i,"state")=="normal" for i in p.items.values()))
        p.cv.event_generate("<KeyRelease-F9>");self.root.update();self.assertFalse(p.raw)
        self.assertEqual(p.cv.itemcget(p.items["rotor","cutoff"],"state"),"normal")

    def test_pitch_properties_back_and_write_review_are_separate_from_undo(self):
        a=self.a;p=self.p;self.mark("mode",3);self.key("pitch")
        p.cv.event_generate("<KeyPress-comma>");self.root.update()
        self.key("fs","<ButtonPress-1>")
        self.assertEqual(a._pat().pitches[0]["note"],"F#3")
        self.assertTrue(a._pat().pitches[0]["accent"])
        self.assertTrue({"fs","accent_key","pitch"}<=p.last_lamps)
        self.key("fs","<ButtonRelease-1>");p.cv.event_generate("<KeyRelease-comma>");self.root.update()
        self.key("back");self.assertEqual(a.pc,0);self.assertEqual(a._pat().pitches[0]["note"],"F#3")
        self.key("write","<ButtonPress-1>");self.assertTrue({"pitch","fs","accent_key"}<=p.last_lamps)
        p.cv.event_generate("<KeyPress-period>");self.root.update()
        self.assertTrue(a._pat().pitches[0]["slide"])
        self.key("write","<ButtonRelease-1>");p.cv.event_generate("<KeyRelease-period>");self.root.update()
        self.key("func");self.assertEqual(a.editor,"Grid")

    def test_timing_wrap_protected_clear_and_original_lamp_not_button_position(self):
        a=self.a;p=self.p;self.mark("mode",3);self.c.press("func")
        for _ in range(3):self.key("down")
        self.c.release("func");self.assertEqual(a._pat().length,3)
        self.key("time");self.key("down");self.key("up","<ButtonPress-1>")
        self.assertEqual(p.last_lamps,{"time","up"});self.key("up","<ButtonRelease-1>");self.key("accent_key")
        self.assertEqual(a._pat().time[:3],["N","T","R"]);self.assertEqual(a.editor,"Grid")
        pitches=[n.copy() for n in a._pat().pitches]
        self.key("clear");self.assertEqual(a._pat().time[0],"N")
        self.c.press("c");self.key("clear");self.c.release("c")
        self.assertEqual((a._pat().length,a._pat().time),(16,["R"]*16))
        self.assertEqual(a._pat().pitches,pitches)

    def test_all_four_groups_and_sections_midi_clock_and_reference_view(self):
        a=self.a;p=self.p
        for d,group in enumerate((0,0,1,1,2,2,3)):
            self.mark("group",d);self.key("slide");self.key("hi_c")
            self.assertEqual(a.cur_bank,16*group+15)
        a.midi=NS();a.sync_arm(False);t=time.monotonic()
        read=lambda x:read_transport(a,x,p.controls.epoch)
        self.assertFalse(read(t).running);a.midi_clock.feed("start",t);a.midi_clock.feed("clock",t)
        self.assertTrue(read(t).running);self.assertIn("run",self.c.lamp_ids(read(t)))
        a.midi_clock.feed("stop",t+.01);self.assertNotIn("run",self.c.lamp_ids(read(t+.011)))
        a._stop();a.midi=None

    def test_live_view_switch_does_not_reopen_audio_and_led_is_not_a_note_chase(self):
        a=self.a;self.key("run");old=a._live
        self.assertIsNotNone(old);self.audio(100)
        a.show_panel("studio");self.root.update()
        self.assertIs(a._live,old);self.assertFalse(self.p.cv.winfo_ismapped())
        a.show_panel("roland");self.root.update();self.assertIs(a._live,old)
        self.key("d");now=read_transport(a,time.monotonic())
        self.assertEqual((now.slot,now.queued),(0,1));self.assertIn("run",self.c.lamp_ids(now))
        remaining=int(math.ceil(old._remaining()-1e-8))
        self.audio(remaining);t=read_transport(a,time.monotonic())
        self.assertEqual(t.slot,1)
        self.assertEqual(self.c.lamp_ids(TransportView(1,running=True,beat_on=True,cell=11)),{"d","accent_key","run"})
        self.key("run");self.assertNotIn("run",self.p.last_lamps)

    def test_track_starts_at_selected_bar_knobs_reach_engine_and_reset_does_not_stop(self):
        a=self.a;self.mark("mode",0);self.key("c");self.key("write");self.key("d");self.key("write")
        self.assertEqual(a.tracks[0].bars,[(0,0),(1,0)])
        self.mark("mode",1);self.key("write");self.assertEqual(a.bar_pos,1);self.key("run")
        player=a._track_player;self.assertIsNotNone(player)
        self.assertEqual(read_transport(a,time.monotonic()).slot,1)
        self.audio(200);self.p.set_fraction("cutoff",.76);self.p.set_fraction("bpm",.5)
        self.assertAlmostEqual(player.engine.params[0],.76);self.assertAlmostEqual(player.engine.params[5],170)
        self.key("clear");self.assertIs(a._track_player,player)
        self.audio(player.limit-player.pos);self.assertEqual(read_transport(a,time.monotonic()).slot,0)
        self.key("run")

    def test_pattern_group_is_locked_during_run_and_a_new_slot_cancels_the_shift(self):
        a=self.a;self.key("run");self.mark("group",4);self.assertEqual(self.c.group,0)
        self.c.press("pitch");self.key("g");self.c.release("pitch")
        self.assertEqual(a._live.snapshot()[1].transpose,7)
        self.key("d");pending=a._live.snapshot()[1]
        self.assertEqual((pending.slot,pending.transpose),(1,0))
        self.assertEqual(a._panel_shift,0);self.key("run");self.mark("group",4);self.assertEqual(self.c.group,4)

    def test_the_volume_switch_blanks_the_lenses_and_does_not_clear_projects(self):
        self.key("run");self.assertTrue(self.a.playing)
        self.p.set_fraction("volume",0.,-1);self.p.set_fraction("volume",0.,-1);self.p.draw()
        self.assertFalse(self.a.playing);self.assertEqual(self.p.last_lamps,set())
        self.key("run");self.assertFalse(self.a.playing)
        self.p.set_fraction("volume",.5,.5);self.p.draw()
        self.assertTrue(self.c.power);self.assertEqual(self.a.kv["volume"],.5)
        self.assertIn("accent_key",self.p.last_lamps)

if __name__=="__main__":unittest.main()
