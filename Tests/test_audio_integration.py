"""Regressions at the boundaries between converter, transport, recorder, and GUI."""
import sys, tempfile, json, unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"Python_Scripts"))
from tb303_rt import RealtimeEngine
import tb303_rt
from classic_sequence import Track, Pattern
from classic_track import Transport
from test_classic import voice,score
from classic_voice import render_engine

class IntegrationTests(unittest.TestCase):
    def test_converter_uses_the_selected_voice(self):
        import audio_to_tb303 as fit
        notes=np.array([36,36,48,39,-1,36,43,36,41,36,48,-1,36,43,39,36])
        slides=np.array([False,True]+[False]*14);accent=notes==39
        grid=fit.Grid(bpm=120,start=0,subdiv=4,shuffle=0.)
        timbre=(.3,.81,.52,.68,.82,0.,.8)
        frames=fit.SR*2
        for profile in ("classic","legacy"):
            renderer=fit.fitting_engine(tb303_rt,profile)
            converted=fit.play(renderer,grid,440,notes,slides,accent,timbre,"saw",frames)
            seq=[dict(note=fit.note_name(n) if n!=-1 else None,slide=sl,accent=ac) for n,sl,ac in zip(notes,slides,accent)]
            e=voice(seq,sr=fit.SR,bpm=120,profile=profile,**dict(zip(fit.FIT_KEYS,timbre)))
            e.set_playing(True);ref=np.empty(frames);e.process(ref)
            np.testing.assert_allclose(converted,ref,atol=1e-12)
            with tempfile.TemporaryDirectory() as td:
                path=Path(td)/"from_audio.tb303"
                fit.write_project(path,grid,"1/16",440,notes,slides,accent,timbre,"saw",profile)
                from tb303_studio import SkinStudio
                self.assertEqual(SkinStudio._read_project(path)["profile"],profile)

    def test_original_16_element_block_api_still_accepts_no_sentinel(self):
        e=voice(["C2"]*16,profile="legacy")
        e.set_playing(True);a=np.empty(25000)
        tb303_rt.synth_block(a,len(a),e.state,e.params,e.pat_f[:16],e.pat_a[:16],e.pat_s[:16],16,float(e.sr))
        self.assertTrue(np.isfinite(a).all())

    def test_audition_does_not_restart_running_voice(self):
        e=voice(["C2~","C3"]);e.set_playing(True);e.process(np.empty(2000))
        st=e.state.copy();e.preview("G3");np.testing.assert_array_equal(st,e.state)

    def test_carry_at_measure_join_is_a_real_slide(self):
        from classic_track import Score,Bar
        def build(slot,shift):
            e=voice([["C2~"],["C3"]][slot],sr=12000,bpm=120)
            return Bar(e,("TB","classic"),(1500.,),(0,))
        s=Score(Track([(0,0),(1,0)]),build,12000);p=Transport(s)
        y=np.empty(3000);p.fill(y)
        e=voice(["C2~","C3"],sr=12000,bpm=120);e.set_playing(True);ref=np.empty(3000);e.process(ref)
        np.testing.assert_allclose(y,ref,atol=1e-12)

    def test_tie_across_two_different_pattern_slots(self):
        from classic_track import Score,Bar
        def build(slot,shift):
            e=voice([["C2"],["="]][slot],sr=12000,bpm=120)
            return Bar(e,("TB","classic"),(1500.,),(0,))
        s=Score(Track([(0,0),(1,0)]),build,12000);p=Transport(s);y=np.empty(3000);p.fill(y)
        e=voice(["C2","="],sr=12000,bpm=120);e.set_playing(True);ref=np.empty(3000);e.process(ref)
        np.testing.assert_allclose(y,ref,atol=1e-12)

