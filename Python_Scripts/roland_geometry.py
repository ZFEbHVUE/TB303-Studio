"""Registration on the supplied 1656 x 814 TB-303 photograph; coordinates are native pixels."""
from dataclasses import dataclass
from math import atan2, degrees, hypot
from pathlib import Path

SIZE=(1656,814)
PHOTO=Path(__file__).resolve().parents[1]/"doc"/"skin"/"Roland_Photo"/"Roland_TB-303_Panel.jpg"

@dataclass(frozen=True)
class Rotor:
    # Bottom disc, top cap and angle of the photographed index, clockwise from noon.
    base:tuple
    cap:tuple
    reference:float
    radius:float
    selector:bool=False

ROTORS={
    "tuning":Rotor((494.9,103,37.4,38.1),(492.4,93.1,24.0,25.2),66,45),
    "cutoff":Rotor((616.0,103,37.5,38.1),(615.6,93.2,24.5,25.8),26,45),
    "resonance":Rotor((738.1,103.2,37.8,38.0),(736.5,93.1,24.3,25.1),155,45),
    "env_mod":Rotor((860.6,103.6,37.8,38.1),(859.4,94.2,24.3,25.5),6,45),
    "decay":Rotor((982.4,103.8,37.5,38.1),(981.3,94.0,24.5,25.5),50,45),
    "accent":Rotor((1104.0,104,37.6,38.2),(1103.4,94.5,24.6,25.6),162,45),
    "bpm":Rotor((247.8,299,57.4,56.1),(237.7,287.4,40.0,40.3),17,68),
    "group":Rotor((492.5,298.9,55.8,56.0),(492.5,298.9,38.5,38.7),52,69,True),
    "mode":Rotor((738.5,298.5,54.9,55.6),(738.5,298.5,37.6,38.0),106,69,True),
    "volume":Rotor((1434,298.4,55.6,54.2),(1446.3,283.8,40.0,40.7),-143,70),
}
# Centre of each panel-printed detent, not evenly spaced virtual positions.
DETENTS={"group":((423,316),(423,278),(441,246),(466,224),(513,225),(545,248),(565,278)),
         "mode":((789,246),(810,279),(811,317),(789,349))}
MODES=("Track Write","Track Play","Pattern Play","Pattern Write")
GROUPS=(0,0,1,1,2,2,3)
def angle(x,y,cx,cy):
    return degrees(atan2(x-cx,cy-y))
def detent_angle(name,i):
    return angle(*DETENTS[name][i],*ROTORS[name].base[:2])
def nearest_mark(x,y):
    for name,marks in DETENTS.items():
        r=ROTORS[name]
        if hypot(x-r.base[0],y-r.base[1])<r.radius-5:continue
        for i,(mx,my) in enumerate(marks):
            if hypot(x-mx,y-my)<=14:return name,i
    return None

PITCH_KEYS=("c","cs","d","ds","e","f","fs","g","gs","a","as","b","hi_c")
WHITES=("c","d","e","f","g","a","b","hi_c")
MOD_KEYS=("down","up","accent_key","slide")
KEYS={
    "clear":(89,493,162,533), "run":(72,588,177,658),
    "pitch":(250,494,322,533),"func":(234,588,272,657),
    "time":(1357,472,1429,510),"back":(1490,493,1563,533),
    "write":(1474,587,1581,659),
}
for name,x in zip(WHITES+MOD_KEYS,(414,503,592,681,770,860,949,1037,1131,1220,1310,1399)):
    KEYS[name]=(x-19,588,x+19,658)
for name,x in zip(("cs","ds","fs","gs","as"),(458,548,726,815,904)):
    KEYS[name]=(x-17,484,x+17,552)

# Lens centres and radii. Not every indicator sits above its own switch:
# the TIME lamp is at 1265, while the TIME button is at 1393.
LEDS={"run":(125,567,8),"normal":(336.5,567.6,8.1),"pitch":(287.2,468.2,7.3),
      "time":(1265,462.8,8.1)}
for name,x in zip(WHITES+MOD_KEYS,(414.4,503.2,592.6,681.4,770.5,859.6,948.6,1037.3,1131.4,1220.8,1309.6,1398.8)):
    LEDS[name]=(x,567.5,8.1)
for name,x in zip(("cs","ds","fs","gs","as"),(459.6,548.8,726.2,815.5,903.9)):
    LEDS[name]=(x,462.7,8.4)

def hit(x,y):
    for name,(l,t,r,b) in KEYS.items():
        if l<=x<r and t<=y<b:return "key",name
    d=nearest_mark(x,y)
    if d:return "mark",d
    for name,k in ROTORS.items():
        if hypot(x-k.base[0],y-k.base[1])<=k.radius:return "rotor",name
    if 152<=x<=254 and 28<=y<=65:return "rear","waveform"
    if 1271<=x<=1398 and 350<=y<=377:return "power","power"
    return None,None

# Mouse users can hold a second physical key using the computer keyboard.
BINDINGS=dict(zip("zsxdcvgbhnjmq",PITCH_KEYS))
BINDINGS.update({"f":"func","Shift_L":"func","Shift_R":"func","p":"pitch","t":"time",
                 "space":"run","Return":"write","KP_Enter":"write","BackSpace":"back",
                 "Delete":"clear","bracketleft":"down","bracketright":"up",
                 "comma":"accent_key","period":"slide"})
