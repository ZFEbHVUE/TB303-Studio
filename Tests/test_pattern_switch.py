"""Real PCM, controller and GUI regression tests for quantized Pattern Play."""
import math, sys, tkinter as tk, unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"Python_Scripts"))
from live_pattern import Program, PatternPlayer, MixerPatterns
from classic_sequence import Pattern
from clock24 import Clock24
from tb303 import parse_step
from tb303_rt import RealtimeEngine
import tb303_studio as studio
import midi_in

def bank(slot,notes,sr=12000,bpm=120,scale="1/16",shuffle=0.,profile="classic",sample=None):
    k={key:limits[2] for key,limits in studio.KNOB_SPEC.items()}
    k.update(bpm=bpm,shuffle=shuffle,cutoff=.34,resonance=.73,env_mod=.54,accent=.7)
    settings=dict(knobs=k,scale=scale,waveform="saw",playmode="Forward")
    return Program(slot,sr,settings,"TB-303" if sample is None else "sample:t",profile,
                   tuple(dict(parse_step(n),cell=i) for i,n in enumerate(notes)),sample)

def render(player,n,chunk=257):
    y=np.empty(n)
    for a in range(0,n,chunk):player.fill(y[a:a+chunk])
    return y

class OutputClockTests(unittest.TestCase):
    def test_request_at_step_11_old_bar_finishes_then_new_note_on_exact_sample(self):
        first=["C2","D2","E2","F2"]*4; first[-1]="B2~"
        last=["E3","F3","G3","A3"]
        for profile in ("classic","legacy"):
            with self.subTest(profile=profile):
                a,b=bank(0,first,profile=profile),bank(1,last,profile=profile)
                p=PatternPlayer(a)
                before=render(p,15500);self.assertEqual(p.heard_cell(),10)
                # Five hundred samples into step 11; five and two-thirds steps remain.
                p.request(b); tail=render(p,8499);self.assertEqual(p.snapshot()[0].slot,0)
                lastold=render(p,1);self.assertEqual(p.snapshot()[0].slot,1)
                after=render(p,5500);self.assertEqual(p.heard_cell(),3)
                actual=np.r_[before,tail,lastold,after]
                ref=bank(5,first+last,profile=profile).make_bar().engine
                ref.set_playing(True);expected=np.empty(len(actual));ref.process(expected)
                np.testing.assert_allclose(actual,expected,atol=1e-12,rtol=1e-10)

    def test_requests_replace_or_cancel_existing_candidate_without_touching_current(self):
        a=bank(0,["C2"]*4)
        p=PatternPlayer(a);p.request(bank(1,["E2"]));render(p,4000)
        p.request(bank(2,["G3"]));render(p,250);p.request(None)
        got=render(p,2500);self.assertEqual(p.snapshot(),(a,None))
        ref=PatternPlayer(a);render(ref,4250);np.testing.assert_equal(got,render(ref,2500))
        p.request(bank(1,["E2"]));p.request(bank(2,["G3"]));render(p,5250)
        self.assertEqual(p.snapshot()[0].slot,2)

    def test_fractional_swing_three_steps_triplets_and_different_target_tempo(self):
        a=bank(0,["C2","G2","A2"],sr=11025,bpm=131,shuffle=.31,scale="1/8T")
        b=bank(5,["F3","D3"],sr=11025,bpm=97,shuffle=.17)
        p=PatternPlayer(a);render(p,2000,73);p.request(b)
        boundary=math.ceil(a.edges()[-1])
        render(p,boundary-2001,71);self.assertEqual(p.snapshot()[0].slot,0)
        # Cross the boundary in the middle of an audio callback, without any Tk tick.
        render(p,202,202)
        self.assertEqual(p.snapshot()[0].slot,5);self.assertEqual(p.heard_cell(),0)
        self.assertAlmostEqual(p.bar.engine.state[9],201+(boundary-a.edges()[-1]),places=6)
        render(p,math.ceil(b.edges()[0])-200)
        self.assertEqual(p.heard_cell(),1)

    def test_live_tempo_change_moves_the_pending_boundary(self):
        a=bank(0,["C2","D2","E2","F2"]);p=PatternPlayer(a)
        render(p,525);p.request(bank(1,["G3"]))
        p.knob(0,"bpm",180);render(p,3474)
        self.assertEqual(p.snapshot()[0].slot,0);render(p,1);self.assertEqual(p.snapshot()[0].slot,1)

    def test_tie_across_banks_and_across_sampler_change(self):
        sample=NS(s=np.sin(np.arange(5000)*.09),base=240.)
        for smp in (None,sample):
            with self.subTest(sampler=smp is not None):
                a,b=bank(0,["C2"],sample=smp),bank(1,["=","G2"],sample=smp)
                p=PatternPlayer(a);p.request(b);audio=render(p,3600,137)
                e=bank(3,["C2","=","G2"],sample=smp).make_bar().engine
                e.set_playing(True);ref=np.empty(3600);e.process(ref)
                np.testing.assert_allclose(audio,ref,atol=1e-12)
        p=PatternPlayer(bank(0,["G2~"])); b=bank(1,["C3","D3"],sample=sample)
        p.request(b);audio=render(p,2000)
        e=b.make_bar().engine;e.set_playing(True);independent=np.empty(500);e.process(independent)
        np.testing.assert_allclose(audio[1500:],independent,atol=1e-12)

    def test_preparing_a_new_candidate_cannot_play_the_displaced_one(self):
        a,b,c=[bank(i,[n]) for i,n in enumerate(("C2","E2","G2"))]
        p=PatternPlayer(a);p.request(b);render(p,1400)
        make=c.make_bar
        def slow():
            render(p,250); self.assertEqual(p.snapshot()[0].slot,0)
            return make()
        with patch.object(c,"make_bar",side_effect=slow):p.request(c)
        self.assertEqual(p.snapshot()[1].slot,2)
        render(p,1350);self.assertEqual(p.snapshot()[0].slot,2)

    def test_external_clock_uses_master_ticks_and_stop_cancels(self):
        a,b=bank(0,["C2","D2","E2"]),bank(1,["A2","B2"],scale="1/8T")
        clock=Clock24();p=PatternPlayer(a,clock);clock.feed("start",0.)
        def tick(i):
            now=i/48.;clock.feed("clock",now)
            data=np.empty(16);p.fill(data,now=now)
        for i in range(11):tick(i)
        p.request(b)
        for i in range(11,18):tick(i)
        self.assertEqual(p.snapshot()[0].slot,0)
        tick(18);self.assertEqual((p.snapshot()[0].slot,p.heard_cell()),(1,0))
        p.request(a);clock.feed("stop",.40);buf=np.ones(20);p.fill(buf,now=.40)
        self.assertTrue(np.all(buf==0));self.assertIsNone(p.snapshot()[1])
        # Armed while stopped: the chosen pattern is ready for the next master START.
        p.request(a);self.assertEqual(p.snapshot()[0].slot,0)
        clock.feed("start",.42);clock.feed("clock",.42);p.fill(buf,now=.42)
        self.assertFalse(p.pulse.waiting);self.assertEqual(p.heard_cell(),0)

class Channel:
    """Sample-consuming SDL contract: at most one queued sound, automatically promoted."""
    def __init__(self):self.sound=self.queued=None;self.pos=0;self.started=0
    def play(self,s):self.sound=s;self.pos=0;self.queued=None;self.started+=1
    def queue(self,s):
        if self.sound is None:self.play(s)
        else:self.queued=s
    def get_sound(self):return self.sound
    def get_queue(self):return self.queued
    def stop(self):self.sound=self.queued=None
    def consume(self,n):
        parts=[]
        while n and self.sound is not None:
            k=min(n,len(self.sound.pcm)-self.pos)
            parts.append(self.sound.pcm[self.pos:self.pos+k]);self.pos+=k;n-=k
            if self.pos==len(self.sound.pcm):
                self.sound,self.queued=self.queued,None;self.pos=0
        return np.concatenate(parts) if parts else np.empty((0,2),np.int16)

class FallbackTests(unittest.TestCase):
    def test_sdl_promotes_only_at_end_stale_results_never_start_old_request(self):
        ch=Channel();pg=NS(mixer=NS(find_channel=lambda force:ch),sndarray=NS(make_sound=lambda pcm:NS(pcm=pcm)))
        a,b,c=[bank(i,[n,n],sr=8000) for i,n in enumerate(("C2","E2","G2"))]
        p=MixerPatterns(a,pg,background=False)
        matches=lambda x,y:np.testing.assert_array_equal(x,y)
        base=a.mixer_samples()
        p.request(b);p.render_one()
        matches(ch.consume(1201),base[:1201])
        p.request(c)  # b was ready, but has not yet sounded. c is still rendering.
        matches(ch.consume(len(base)-1201),base[1201:])
        self.assertEqual(p.snapshot()[0].slot,0)
        self.assertEqual(p.snapshot()[1].slot,2);self.assertTrue(p.render_one())
        ch.consume(len(base)-1);self.assertEqual(p.snapshot()[0].slot,0)
        ch.consume(1);self.assertEqual(p.snapshot()[0].slot,2)
        matches(ch.consume(235),c.mixer_samples()[:235])
        p.request(b);p.request(None);ch.consume(len(base)-235);self.assertEqual(p.snapshot()[0].slot,2)
        self.assertEqual(ch.started,1);p.finish();self.assertIsNone(ch.get_sound())

class StudioSwitchTests(unittest.TestCase):
    def setUp(self):
        try:self.root=tk.Tk()
        except tk.TclError as exc:raise unittest.SkipTest(str(exc))
        self.errors=[];self.root.report_callback_exception=lambda _,exc,tb:self.errors.append(exc)
        with patch.object(studio,"_HAS_RT",False),patch.object(studio,"_HAS_PYGAME",False):
            self.a=studio.SkinStudio(self.root,studio._find_skin())
        self.root.update()
        self.a.SR=12000
        self.host=RealtimeEngine(self.a.SR);self.host.stream=NS(active=True)
        self.a.rt=self.host;self.a.mode="rt";self.a.audio_ok=True
        for slot,notes in [(0,["C2"]*16),(1,["D2","E2","F2"]),(2,["A3"]*4)]:
            a=self.a;a._switch_bank(slot);a.patterns[slot]=Pattern.from_grid([parse_step(n) for n in notes])
            a.patterns[slot].length=len(notes);a.kv["bpm"]=120;a._paint_pattern()
        self.a._switch_bank(0)

    def tearDown(self):
        self.host.stream=None;self.a.close();self.root.destroy();self.assertEqual(self.errors,[])

    def audio(self,n):
        out=np.empty((n,2),np.float32);self.host._callback(out,n,None,None);return out
    def click(self,slot):
        a=self.a
        x=round(a.S(a.M["banks"][slot]));y=round(a.S(a.M["banks_y"]))
        for event in ("<ButtonPress-1>","<ButtonRelease-1>"):
            a.cv.event_generate(event,x=x,y=y);self.root.update_idletasks()

    def test_same_path_for_pad_mouse_cancel_and_stop_no_ui_timer_required(self):
        a=self.a;a._toggle_run();self.audio(15500)
        self.click(1);self.assertEqual((a.cur_bank,a._pending_bank),(0,1))
        self.assertEqual(a._face.texts[1],"NEXT: 1A-2");self.assertTrue(a.cv.find_withtag("queued_bank"))
        m=object.__new__(midi_in.MidiBridge);m.app=a;m.verbose=False;m._draw_badge=lambda:None
        m._pad(midi_in.PAD_FIRST+2);self.assertEqual(a._pending_bank,2)
        self.click(0);self.assertIsNone(a._pending_bank)
        self.click(2);self.audio(8499);self.assertEqual(a._live.snapshot()[0].slot,0)
        self.audio(500);self.assertEqual(a._live.snapshot()[0].slot,2)
        a._poll_live();self.assertEqual((a.cur_bank,a._pending_bank,a._pat().length),(2,None,4))
        self.assertFalse(a.cv.find_withtag("queued_bank"))
        self.click(1);a._toggle_run();self.assertFalse(a.playing);self.assertIsNone(a._pending_bank)
        a._toggle_run();self.audio(6500);self.assertEqual(a._live.snapshot()[0].slot,2)
        a._stop();self.click(1);self.assertEqual(a.cur_bank,1)

    def test_forward_reverse_finishes_the_return_and_respects_target_order(self):
        a=self.a;a._switch_bank(1);a.playmode_v.set("Fwd&Rev");a._changed()
        a._switch_bank(2);a.playmode_v.set("Reverse");a._changed()
        a._switch_bank(1);a._toggle_run();self.audio(4501)
        self.click(2);self.audio(4498)
        self.assertEqual(a._live.snapshot()[0].slot,1)  # completed forward, still returning
        self.audio(2);self.assertEqual(a._live.snapshot()[0].slot,2)
        self.assertEqual(a._live.heard_cell(),3)       # first PLAYED event in reverse

    def test_switch_during_take_and_while_ui_is_busy_does_not_restart_stream(self):
        a=self.a;a._toggle_run();captured=[]
        self.host.output_tap=lambda x:captured.append(x.copy())
        before=self.audio(17003);self.click(1)
        rest=self.audio(8300)  # single audio callback crossing the boundary while Tk is idle
        self.assertEqual(a._live.snapshot()[0].slot,1);a._poll_live()
        self.assertIs(self.host.track_source,a._live);self.assertIs(self.host,a._active_engine())
        np.testing.assert_array_equal(np.vstack(captured),np.vstack((before,rest)))
        self.assertIsNotNone(self.host.output_tap)

