"""Run: python -m unittest discover -s Tests -v (Tk tests need a display)."""
import math, os, sys, tempfile, unittest, wave, json, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from contextlib import contextmanager
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"Python_Scripts"))
import numpy as np
import tkinter as tk
from classic_sequence import Pattern, Track, label
from classic_voice import render_engine
from classic_track import Bar, Score, Transport, export_score
from clock24 import Clock24, PulseTransport
import tb303_studio as studio
import midi_in
from tb303 import note_to_freq
from tb303_rt import RealtimeEngine
from instruments_rt import RealtimeSamplerEngine
from live_recording import WaveTake

def voice(notes,sr=12000,bpm=125,div=4,profile="classic",**params):
    e=RealtimeEngine(sr);e.set_profile(profile)
    for k,v in dict(bpm=bpm,subdiv=div,**params).items(): e.set_param(k,v)
    e.set_pattern(notes)
    return e

def score(track=None,sr=12000,bpm=125):
    if track is None: track=Track([(0,0),(1,0),(2,0)],0,2)
    def make(slot,shift):
        notes=[["C2+~","G2"],["D2","=","."],["E2+"]][slot]
        e=voice(notes,sr,bpm)
        e.pat_f[:len(notes)] = np.where(e.pat_f[:len(notes)]>0,e.pat_f[:len(notes)]*2**(shift/12),e.pat_f[:len(notes)])
        n=e.nsteps; return Bar(e,("TB-303","classic"),tuple((i+1)*sr*60./bpm/4 for i in range(n)),tuple(range(n)))
    return Score(track,make,sr)

class SequenceTests(unittest.TestCase):
    def test_pitches_not_consumed_by_ties_or_rests(self):
        p=Pattern(); p.length=4
        for i,n in enumerate(("C2","E2","G2")): p.write_pitch(i,n)
        for i,k in enumerate("NTRN"): p.write_time(i,k)
        self.assertEqual([x["note"] for x in p.grid(True)],["C2",None,None,"E2"])
        self.assertTrue(p.grid()[1]["tie"])
        r=Pattern.read(json.loads(json.dumps(p.dump())))
        r.write_time(2,"N")
        self.assertEqual([x["note"] for x in r.grid(True)],["C2",None,"E2","G2"])

    def test_shortening_is_reversible_and_ins_del_are_local(self):
        p=Pattern.from_grid(["C2", "D2", "E2", "F2", "A3"]+["."]*11)
        p.length=4; p.shift_cell(1,False)
        self.assertEqual([x["note"] for x in p.grid()[:5]],["C2","E2","F2",None,"A3"])
        p.shift_cell(1,True); self.assertEqual([s["note"] for s in p.grid()[:5]],["C2",None,"E2","F2","A3"])

    def test_labels_and_track_markers(self):
        self.assertEqual([label(i) for i in (0,7,8,16,63)],["1A-1","1A-8","1B-1","2A-1","4B-8"])
        t=Track([(0,0),(8,3),(63,-12)],1,2)
        t.put(0,16,5,True); self.assertEqual((t.segno,t.dc),(2,3))
        t.remove(0);self.assertEqual(t.after(2,"ds"),1);self.assertEqual(t.after(2),0)
        self.assertEqual(t.after(1,"reset"),0)
        with self.assertRaises(ValueError): t.mark("segno",2)
        t.remove(1);self.assertIsNone(t.segno);self.assertEqual(t.dc,1)

    def test_malformed_project_data_rejected(self):
        d=Pattern().dump();d["length"]=0
        with self.assertRaises(ValueError):Pattern.read(d)
        with self.assertRaises(ValueError):Track.read({"bars":[[64,0]]})
        with self.assertRaises(ValueError):Pattern.from_grid(["H2"])

class AudioTests(unittest.TestCase):
    def test_classic_callback_and_bounce_same_samples(self):
        notes=["C2+~","G2","=",".","D#2+"]
        params=dict(swing=.29,bpm=123.5,distortion=.16)
        audio=render_engine(voice(notes,**params),2)
        e=voice(notes,**params);e.set_playing(True)
        chunks=[]
        for i in range(0,len(audio),137):
            out=np.empty((min(137,len(audio)-i),2),np.float32); e._callback(out,len(out),None,None);chunks.append(out)
        np.testing.assert_array_equal(audio.astype(np.float32),np.vstack(chunks))

    def test_slide_pitch_continuous_and_no_legato_retrigger(self):
        sr=12000;n=sr*60//120//4
        e=voice(["C2~","C3"],sr,bpm=120);e.set_playing(True);e.process(np.empty(n))
        e.process(np.empty(1)); first=2**e.state[7]; env=e.state[5]
        self.assertTrue(note_to_freq("C2")<first<note_to_freq("C2")*1.01)
        e.process(np.empty(round(.06*sr)));self.assertGreater(2**e.state[7],.95*note_to_freq("C3"))
        self.assertLess(env,.97)
        e=voice(["C2","C3"],sr,bpm=120);e.set_playing(True);e.process(np.empty(n+1));self.assertGreater(e.state[5],.99)

    def test_tie_holds_pitch_versus_rest_and_no_ghost(self):
        a=render_engine(voice(["C2","=","."]))[:,0]; b=render_engine(voice(["C2",".","."]))[:,0]
        n=len(a)//3
        self.assertGreater(np.sqrt(np.mean(a[n:n+n//3]**2)),10*np.sqrt(np.mean(b[n:n+n//3]**2)))
        self.assertFalse(np.any(render_engine(voice(["=",".", "="]))))

    def test_accent_decay_independent_and_unaccented_adjustable(self):
        def env(note,dec):
            e=voice([note],decay=dec);e.set_playing(True);e.process(np.empty(750));return e.state[5]
        self.assertAlmostEqual(env("C2+",.1),env("C2+",.95),places=12)
        self.assertGreater(env("C2",.95),env("C2",.1))

    def test_resonant_accent_remembers_previous_note(self):
        e=voice(["C2+","C2+"],bpm=240,resonance=1.);e.set_playing(True)
        e.process(np.empty(300)); first=e.state[18]
        e.process(np.empty(750)); self.assertGreater(e.state[18],first)

    def test_output_bounded_at_extremes(self):
        for c,r,w in [(0,1,"square"),(1,1,"saw"),(.2,0,"saw")]:
            a=render_engine(voice(["C1+~","G4+","=","."],cutoff=c,resonance=r,waveform=w,distortion=1.))
            self.assertTrue(np.isfinite(a).all());self.assertLess(np.abs(a).max(),1.)

    def test_track_blocks_loop_and_export(self):
        s=score(bpm=127.3);p=Transport(s);a=np.empty(s.frames);p.fill(a)
        self.assertEqual((p.index,p.rounds),(0,1))
        p=Transport(score(bpm=127.3));b=np.empty(len(a))
        for i in range(0,len(b),197):p.fill(b[i:i+197])
        np.testing.assert_allclose(a,b,atol=1e-12)
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"track.wav";export_score(score(bpm=127.3),path)
            with wave.open(str(path)) as wav:
                self.assertEqual((wav.getnchannels(),wav.getframerate(),wav.getnframes()),(2,12000,len(a)))
                pcm=np.frombuffer(wav.readframes(len(a)),"<i2").reshape(-1,2)
            np.testing.assert_array_equal(pcm[:,0],(a*32767).astype(np.int16))

    def test_ds_deferred_and_precedes_dc(self):
        p=Transport(score(Track([(0,0),(1,0),(2,0)],1,2)))
        p.fill(np.empty(p.limit));self.assertEqual(p.index,1)
        p.fill(np.empty(p.limit));p.fill(np.empty(17));p.request("ds")
        self.assertEqual(p.index,2);p.fill(np.empty(p.limit-17));self.assertEqual(p.index,1)
        p.request("reset");p.fill(np.empty(p.limit));self.assertEqual(p.index,0)

    def test_midi_start_stop_continue_and_missing_clock(self):
        c=Clock24();dt=60/120/24.; s=score();p=PulseTransport(s,c);c.feed("start",0.)
        buf=np.ones(128);p.fill(buf,0.);self.assertTrue(np.all(buf==0))
        for i in range(13):
            c.feed("clock",i*dt);p.fill(buf,i*dt)
            if i==6:self.assertEqual((p.index,p.heard_cell()),(0,1))
        self.assertEqual((p.index,p.heard_cell()),(1,0))
        c.feed("stop",13*dt);p.fill(buf,13*dt);self.assertFalse(np.any(buf))
        c.feed("continue",1.);c.feed("clock",1.+dt);self.assertEqual(c.tick,13)
        p.fill(buf,3.);self.assertFalse(np.any(buf))
        c.feed("start",4.);c.feed("clock",4.);p.fill(buf,4.);self.assertEqual((p.index,p.heard_cell()),(0,0))

    def test_sampler_tie_does_not_restart_sample(self):
        e=RealtimeSamplerEngine(sr=12000); e.set_sample(np.sin(np.arange(8000)*.3),130.8)
        e.set_param("bpm",120);e.set_pattern(["C3","=","D3"]);e.set_playing(True)
        e.process(np.empty(1500));pos=e.state[0];e.process(np.empty(1));self.assertGreater(e.state[0],pos)
        e.process(np.empty(1500));self.assertLess(e.state[0],10)

    def test_track_record_tap_sees_exact_output(self):
        s=score();p=Transport(s);host=voice(["C2"]);host.track_source=p
        take=WaveTake(12000);host.output_tap=take.capture_float
        try:
            buf=np.empty((600,2),np.float32);host._callback(buf,len(buf),None,None);take.finish()
            with tempfile.TemporaryDirectory() as td:
                path=str(Path(td)/"take.wav");take.save(path)
                with wave.open(path) as f:pcm=np.frombuffer(f.readframes(600),"<i2").reshape(-1,2)
            np.testing.assert_allclose(pcm,buf*32767,atol=1)
        finally:take.close()

class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try: cls.root=tk.Tk()
        except tk.TclError as exc: raise unittest.SkipTest(f"Tk display unavailable: {exc}")
        cls.root.withdraw()
        cls.errors=[]
        cls.root.report_callback_exception=lambda kind,exc,tb:cls.errors.append(exc)

    @classmethod
    def tearDownClass(cls): cls.root.destroy()

    def setUp(self):
        self.patches=[patch.object(studio,"_HAS_RT",False),patch.object(studio,"_HAS_PYGAME",False)]
        for p in self.patches:p.start()
        self.r=tk.Toplevel(self.root); self.a=studio.SkinStudio(self.r,studio._find_skin())
        self.r.update()

    def tearDown(self):
        self.a.close()
        if self.a._classic_win is not None:self.a._classic_win.destroy()
        self.r.destroy()
        for p in self.patches[::-1]:p.stop()
        self.assertEqual(self.errors,[])

    def test_navigation_then_undo_redo_branch(self):
        a=self.a;a.cursor(0);old=a.steps[0].copy();a._set_note("F#2")
        a.navigate(1);a.navigate(-1);a._switch_bank(63);self.assertEqual(len(a.hist.past),1)
        a.history_move();self.assertEqual((a.cur_bank,a.sel,a.steps[0]),(0,0,old))
        a.history_move(True);self.assertEqual(a.steps[0]["note"],"F#2")
        a.history_move();a._set_note("D2");self.assertFalse(a.hist.future)

    def test_midi_legato_navigation_and_coalesced_knob(self):
        a=self.a;a._clear();bridge=object.__new__(midi_in.MidiBridge);bridge.app=a;bridge.held=set();bridge.mode="write"
        bridge._last_key_t=0;bridge.verbose=False;bridge.KNOB_SPEC=studio.KNOB_SPEC;bridge._draw_badge=lambda:None
        bridge._key_down(SimpleNamespace(note=48,velocity=100));bridge._last_key_t=0
        bridge._key_down(SimpleNamespace(note=52,velocity=50));self.assertTrue(a.steps[0]["slide"])
        self.assertFalse(a.steps[1]["slide"])
        n=len(a.hist.past);bridge._action("prev_step");bridge._action("next_step")
        self.assertEqual(len(a.hist.past),n);a.history_move()
        self.assertFalse(a.steps[0]["slide"]);self.assertIsNone(a.steps[1]["note"])
        v=a.kv["cutoff"];bridge._set_knob("cutoff",.8);bridge._set_knob("cutoff",.6)
        a.history_move();self.assertEqual(a.kv["cutoff"],v)

    def test_project_preserves_unconsumed_pitches_banks_and_track(self):
        a=self.a;a._switch_bank(63);a._clear();a.mode_select("Pitch")
        for n in ("C2","D2","G2"):a._set_note(n)
        a.mode_select("Time");a.set_length(3)
        for k in "NTR":a.time_write(k)
        a.track_edit("write",63,7);s=a._project_state()
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"file.tb303";path.write_text(json.dumps(s))
            a._load_all(a._read_project(path),str(path))
        self.assertEqual((a.cur_bank,a._pat().length,a.tracks[0].bars),(63,3,[(63,7)]))
        self.assertEqual([p["note"] for p in a._pat().pitches],["C2","D2","G2"])
        self.assertEqual(a._pat().time[:3],["N","T","R"])
        self.assertFalse(a.hist.past)
        partial=a._project_state([63]);self.assertEqual(partial["tracks"],[])

    def test_all_original_projects_load_and_roundtrip(self):
        for path in sorted((ROOT/"Projects").glob("*.tb303")):
            p=self.a._read_project(path)
            if p["profile"]!="legacy":continue
            self.a._load_all(p,str(path));out=self.a._project_state()
            self.assertEqual(len(out["banks"]),64);self.assertEqual(out["voice_profile"],"legacy")
            for i,bank in enumerate(p["banks"]):
                if bank is not None:self.assertEqual(out["banks"][i],bank)

    def test_tk_panels_project_dialogs_and_all_skins(self):
        a=self.a;before=a.steps.copy()
        for key in a._skins:
            a.skin_v.set(key);a._change_skin();self.r.update_idletasks()
        self.assertEqual(before,a.steps);self.assertEqual(len(a._skins),11)
        a.show_classic();w=a._classic_win;self.r.update()
        self.assertEqual(len(w.cells),16);self.assertLess(w.winfo_reqheight(),700)
        a.set_length(12);self.assertTrue(w.cells[12].instate(["disabled"]))
        w.show(1);a.track_edit("write",63,5);self.assertIn("4B-8",w.rows.get(0))
        def cancel_new():
            for item in self.r.winfo_children():
                if isinstance(item,(studio.PatternDialog,studio.AudioImportDialog)):item.destroy()
        self.r.after(90,cancel_new)
        dlg=studio.PatternDialog(self.r,"Patterns",[(i,"demo") for i in range(64)],"load")
        self.assertIsNone(dlg.result)
        self.r.after(90,cancel_new);dlg=studio.AudioImportDialog(self.r,"demo",["empty"]*64,63)
        self.assertIsNone(dlg.result)

    def test_legacy_file_sound_profile_and_random_export(self):
        a=self.a;a._load_all(a._read_project(ROOT/"Projects/acid_line.tb303"),str(ROOT/"Projects/acid_line.tb303"))
        self.assertEqual(a.profile,"legacy");baseline=a._render(1)
        a.voice_profile("classic");a.playmode_v.set("Random");a._select_combo("playmode")
        a._order_live();order=list(a._play_cells);a._render(1);self.assertEqual([s["cell"] for s in a._ordered()],order)
        a.history_move();self.assertEqual(a.playmode_v.get(),"Forward");a.history_move()
        np.testing.assert_array_equal(baseline,a._render(1))

if __name__=="__main__":unittest.main()

