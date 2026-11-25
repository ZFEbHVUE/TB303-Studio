"""Classic voice for the Studio. The very same kernel drives audition, live and WAV.
Approximation informed by Roland's manuals and R. Whittle, not a component simulation.
"""
import math
import numpy as np
try:
    from numba import njit
except Exception:
    def njit(**kw):
        return lambda f: f

# Same public parameter layout as the original engine. State 0..16 keeps
# transport and audition compatible with its host; extra cells are per voice.
@njit(cache=True)
def _edge(p, d):
    if p < d:
        v = p/d
        return 2*v-v*v-1
    if p > 1-d:
        v=(p-1)/d
        return v*v+2*v+1
    return 0.


@njit(cache=True)
def classic_block(out, frames, s, p, freqs, accents, slides, count, sr):
    cut,res,env,dec,amt,bpm,dist,vol,wave,div,gatefrac,swing,tune,run = p[:14]
    base=34.*(7200./34.)**cut
    normal=math.exp(-1./(sr*(.20*10.**dec)))
    fast=math.exp(-1./(sr*.20))
    vfade=math.exp(-1./(sr*3.4))
    glide=1.-math.exp(-1./(sr*.020))   # 95% of log-pitch interval in ~60 ms
    attack=1.-math.exp(-1./(sr*.003))
    release=1.-math.exp(-1./(sr*.004))
    rise=1.-math.exp(-1./(sr*(.001+.048*res*res)))
    fall=1.-math.exp(-1./(sr*(.035+.13*res)))
    charge_decay=fall_complement(sr,res)
    q=3.75*res
    duration=sr*60./max(bpm,1.)/max(div,1.)
    phase,z1,z2,z3,z4,meg,amp,logf = s[:8]
    step=int(s[8])%count
    age,gate,acc,was_slide,init,target = s[9:15]
    preview,remaining=s[15:17]
    sweep,vca,charge=s[18:21]
    sd=duration*(1.+swing if step%2==0 else 1.-swing)
    for i in range(frames):
        if run>.5:
            if init<.5 or age>=sd:
                if init>=.5:
                    age-=sd
                    step=(step+1)%count
                else:
                    step=0
                    init=1.
                sd=duration*(1.+swing if step%2==0 else 1.-swing)
                freq=freqs[step]
                if freq>0:
                    target=math.log2(max(1.,freq*tune/440.))
                    acc=accents[step]
                    if was_slide<.5 or gate<.5:
                        logf=target
                        meg=1.
                        vca=1.
                    if acc>.5:
                        charge=min(1.5,charge+.58+.25*res)
                    gate=1.
                    was_slide=slides[step]
                elif freq != -2.:             # rest: a following tie must be silent
                    gate=0.
                    acc=0.
                    was_slide=0.
                # tie: never retrigger, keep the pitch and outgoing slide.
            following=freqs[step+1]           # sentinel = first step of next loop/bar
            held=was_slide>.5 or following==-2.
            on=gate>.5 and (held or age<gatefrac*sd)
            age+=1.
        else:
            if remaining<=0.:
                out[i]=0.
                continue
            if init<.5:
                logf=math.log2(max(1.,preview))
                target=logf
                meg=1.
                vca=1.
                acc=0.
                init=1.
            on=remaining > min(.035*sr,.25*s[21])
            remaining-=1.
        logf+=glide*(target-logf)
        dt=min(.45,2.**logf/sr)
        osc=2.*phase-1.-_edge(phase,dt)
        if wave>.5:
            # Pulse width of the original varies with pitch; 50% near 85 Hz on
            # Burnett's measured unit. The slope and clamps are approximations.
            duty=min(.76,max(.18,.5-.075*(logf-6.409390936)))
            b=(phase-duty)%1.
            osc=(1. if phase<duty else -1.)-(2.*duty-1.)+_edge(phase,dt)-_edge(b,dt)
        phase=(phase+dt)%1.
        meg*=fast if acc>.5 else normal
        vca*=vfade
        charge*=charge_decay
        drive=amt*(meg*acc + .55*res*charge)
        sweep+=(rise if drive>sweep else fall)*(drive-sweep)
        fc=min(.40*sr,max(20.,base*2.**((.40+4.8*env)*meg+1.65*sweep)))
        # Four trapezoidal one-poles with offset first pole; solve the linear
        # feedback loop before soft input saturation, no one-sample feedback lag.
        a=math.tan(math.pi*fc/sr)
        g=a/(1.+a)
        a0=math.tan(math.pi*min(.44,2.6*fc/sr))
        g0=a0/(1.+a0)
        memory=(1.-g)*z4+g*((1.-g)*z3+g*((1.-g)*z2+g*(1.-g0)*z1))
        fb=(osc*(1.+.28*res)-q*memory)/(1.+q*g0*g*g*g)
        y1=z1+g0*(math.tanh(fb)-z1); z1=2.*y1-z1
        y2=z2+g*(y1-z2); z2=2.*y2-z2
        y3=z3+g*(y2-z3); z3=2.*y3-z3
        y4=z4+g*(y3-z4); z4=2.*y4-z4
        av=(.72*vca+amt*.24*acc*meg+.38*sweep) if on else 0.
        amp+=(attack if av>amp else release)*(av-amp)
        y=y4*(2.3+.8*res)*amp
        if dist>0:
            k=1.+18.*dist
            y=math.tanh(k*y)/math.tanh(k)
        out[i]=math.tanh(y*vol)
    s[0]=phase; s[1]=z1; s[2]=z2; s[3]=z3; s[4]=z4
    s[5]=meg; s[6]=amp; s[7]=logf; s[8]=step; s[9]=age
    s[10]=gate; s[11]=acc; s[12]=was_slide; s[13]=init; s[14]=target
    s[16]=remaining; s[18]=sweep; s[19]=vca; s[20]=charge


@njit(cache=True)
def fall_complement(sr,res):
    return math.exp(-1./(sr*(.050+.16*res)))


def render_engine(engine, repeats=1):
    """One transport, fractional step lengths, continuous joins, fixed gain."""
    engine.set_playing(True)
    p=engine.params
    length=engine.nsteps
    samples=engine.sr*60./p[5]/p[9]*sum(1.+p[11]*(-1)**i for i in range(length))
    n=max(1,int(round(samples*repeats)))
    out=np.empty(n,np.float64)
    for a in range(0,n,4096):
        engine.process(out[a:a+4096])
    return np.column_stack((out,out))

