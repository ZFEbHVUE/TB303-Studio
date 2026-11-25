"""Machining coordinates in original art pixels. All button bounds are half-open."""
from dataclasses import dataclass
from pathlib import Path

WIDTH, SOURCE_HEIGHT = 1817, 866
SEAM, UPPER = 554, 99
LOWER_SEAM, LOWER = 671, 145
BAY = UPPER + LOWER
HEIGHT = SOURCE_HEIGHT + BAY
ART = Path(__file__).resolve().parents[1] / "doc" / "skin" / "Inlaid_MkIII"
LCD = (1292, 234, 1569, 290)  # relative to SEAM, as are the switch beds
SKIN_NAMES = ("steampunk", "steampunk_ii", "classic", "acid_rave", "cyberpunk",
              "hard_cyberpunk", "goa_trance", "trance_dub", "dub", "reggae", "cyber_reggae")

@dataclass(frozen=True)
class Key:
    id: str
    text: str
    box: tuple
    source: str
    glyph: str = ""

KEYS = {}
def add(ident, text, x, y, w, h, source="neutral", glyph=""):
    KEYS[ident] = Key(ident, text, (x,y,x+w,y+h), source, glyph)

# The upper switch bank follows the transport, keyboard and articulation areas.
add("back","BACK",263,8,135,78,"stop","undo")
add("redo","REDO",409,8,135,78,"run","redo")
add("prev","PREV",568,34,102,48,"neutral")
add("next","NEXT",680,34,103,48,"neutral")
add("grid","GRID",822,29,111,55,"blue")
add("pitch","PITCH",942,29,116,55,"blue")
add("time","TIME",1067,29,111,55,"blue")
add("note","NOTE",1231,30,110,53,"neutral")
add("tie","TIE",1351,30,97,53,"neutral")
add("rest","REST",1458,30,108,53,"neutral")

# Pattern steps occupy the original illustrated keybed between these two groups.
add("ins","INS",298,239,106,51,"neutral")
add("del","DEL",413,239,108,51,"neutral")
add("write","WRITE / NEXT",531,236,192,55,"blue")
add("shorter","LEN −",300,300,132,50,"neutral")
add("longer","LEN +",441,300,132,50,"neutral")
add("tap","TAP",585,297,138,54,"blue")
add("track_write","TRACK WRITE",775,237,200,54,"blue")
add("track_play","TRACK PLAY",988,237,197,54,"run")
add("bar_prev","BAR −",775,300,113,50,"neutral")
add("bar_next","BAR +",898,300,113,50,"neutral")
add("reset","BAR RESET",1020,298,165,53,"stop")
add("group","GROUP",1214,302,127,49,"neutral")
add("section","A / B",1352,302,108,49,"neutral")
add("track","TRK #",1470,302,115,49,"neutral")

def hit(x,y):
    for key in KEYS.values():
        l,t,r,b=key.box
        if l<=x<r and t<=y<b:
            return key.id
    return None

def panel_map(mapping):
    """Move interactive geometry exactly as far as its original painted control."""
    result = dict(mapping)
    result["cells"] = {**mapping["cells"], "cy": mapping["cells"]["cy"] + UPPER}
    result["buttons"] = {k: (x,y+(BAY if y>=LOWER_SEAM else 0),w,h)
                         for k,(x,y,w,h) in mapping["buttons"].items()}
    x,y=mapping["status"]
    result["status"] = (x,y+BAY)
    return result

def bay_x(x):
    """Native pointer coordinates, also used by external editing scripts."""
    return x

