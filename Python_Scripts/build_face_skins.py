"""Build each instrument from its own photographed or illustrated fittings.

From the project folder: python Python_Scripts/build_face_skins.py [skin ...]
The app ships the results; Python, NumPy and Pillow suffice to rebuild them.
The factory control beds, step keys and footer are never painted over.
"""
import argparse
from functools import lru_cache
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
from face_layout import ART, WIDTH, SEAM, UPPER, LOWER_SEAM, LOWER, BAY, HEIGHT, SOURCE_HEIGHT, KEYS, LCD, SKIN_NAMES

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "doc" / "skin" / "Inlay_Sources"
AA = Image.Resampling.LANCZOS
FILM_TOP, FILM_END = 530, 838
PACK_W, PACK_H, COLS = 204, 80, 6
PACK_SIZE = (COLS*PACK_W, ((len(KEYS)+COLS-1)//COLS)*PACK_H*2)
# Each material swatch is an unoccupied piece of the corresponding instrument.
# Slots are stable even when the registry is reordered.
SWATCH = dict(zip(SKIN_NAMES,(0,1,2,3,4,5,6,7,8,9,10)))
STYLE = {
    # Main lettering, secondary engraving, glass phosphor, contact lamp.
    "steampunk": ("f1d89c","e7ca8d","ffda88","ffbf59"),
    "steampunk_ii": ("ffe8aa","e9d18e","a4f7d8","6cffe4"),
    "classic": ("302c2b","3c3838","e1ebe5","d6332b"),
    "acid_rave": ("efffbb","eeff8e","dbff8f","e2ff36"),
    "cyberpunk": ("c0faff","b4fdff","75f8ff","56ffff"),
    "hard_cyberpunk": ("ffe7a5","ffce84","ffc378","ff9c3b"),
    "goa_trance": ("fff0ff","ffdcf9","c5fff0","73ffde"),
    "trance_dub": ("e2f2ff","d8e6ff","c4deff","7feaff"),
    "dub": ("ffdeae","f3d1a0","ffe5b2","ffba66"),
    "reggae": ("fff0b3","ffe392","ffdf99","fff06a"),
    "cyber_reggae": ("d2ffbc","d1ffc3","c2ffb4","9aff75"),
}

def color(s):
    return tuple(bytes.fromhex(s))

def legend_family(name):
    """One type family for painted keys, value fields and open selector lists."""
    return "serif" if name in ("steampunk","steampunk_ii","custom") else "sans"

@lru_cache(maxsize=180)
def font(size, family):
    filename=("DejaVuSerifCondensed-Bold.ttf" if family=="serif" else "DejaVuSansCondensed-Bold.ttf")
    return ImageFont.truetype(str(DESIGN / filename),size)

def letter(im, xy, value, size, width, ink, family, shadow, max_height=None):
    f=font(size,family)
    while size>8:
        box=f.getbbox(value)
        if box[2]-box[0]<=width and (max_height is None or box[3]-box[1]<=max_height):
            break
        size-=1; f=font(size,family)
    l,t,r,b=f.getbbox(value)
    x=round(xy[0]-(r-l)/2-l); y=round(xy[1]-(b-t)/2-t)
    d=ImageDraw.Draw(im)
    if shadow is not None:
        d.text((x+1,y+1),value,font=f,fill=shadow)
    d.text((x,y),value,font=f,fill=ink)

def smooth(x):
    t=np.clip(x,0,1)
    return t*t*(3-2*t)

def seams():
    # Route the new woodwork around the whole STOP, outer carvings and original
    # step carrier. All original pixels keep their order in every column.
    x=np.arange(WIDTH)
    left=1-smooth((x-239)/51)
    right=smooth((x-1558)/134)
    top=np.rint(SEAM+49*left+12*right).astype(int)
    bottom=np.rint(LOWER_SEAM-59*left-48*right).astype(int)
    return top,bottom

def source_path(name):
    return (ROOT/"docs"/"tb303_skin.png" if name=="steampunk"
            else ROOT/"doc"/"skin"/("tb303_skin_"+name+".png"))

def swatch(original, name):
    path=DESIGN/"chassis_materials.jpg"
    if name!="custom" and path.is_file():
        with Image.open(path) as sheet:
            q=SWATCH[name]; c=q%3; r=q//3
            x,X=round(c*sheet.width/3)+4,round((c+1)*sheet.width/3)-4
            y,Y=round(r*sheet.height/4)+4,round((r+1)*sheet.height/4)-4
            return np.asarray(sheet.crop((x,y,X,Y)).convert("RGB"))
    # Unknown themes contribute their own chassis material as well as their own keys.
    return np.asarray(original.crop((1016,504,1520,544)).convert("RGB"))

def mirrored(coord, length):
    q=np.mod(coord,2*(length-1)); return np.minimum(q,2*(length-1)-q).astype(int)

def extend_body(original, name):
    a=np.asarray(original.convert("RGB"))
    first,second=seams()
    xs=np.arange(WIDTH)[None,:]; ys=np.arange(HEIGHT)[:,None]
    second_out=second+UPPER
    count=(ys>=first+UPPER).astype(int)*UPPER+(ys>=second_out+LOWER).astype(int)*LOWER
    lookup=np.clip(ys-count,0,SOURCE_HEIGHT-1)
    body=a[lookup,xs].copy()
    tex=swatch(original,name); th,tw=tex.shape[:2]
    for index,(seam,start,depth) in enumerate(((first,first,UPPER),(second,second_out,LOWER))):
        v=np.arange(depth)[:,None]; xx=np.arange(WIDTH)[None,:]
        # Independently continue the colour and illumination on each side of the cut.
        before=a[np.maximum(0,seam-1),np.arange(WIDTH)].astype(float)
        after=a[seam,np.arange(WIDTH)].astype(float)
        t=v/(depth-1)
        edge=before[None,:,:]*(1-t[:,:,None])+after[None,:,:]*t[:,:,None]
        native=np.asarray(Image.fromarray(edge.astype(np.uint8)).filter(ImageFilter.GaussianBlur(13)),dtype=float)
        if name=="custom":
            tx=mirrored(xx*.84+index*193+.19*v,tw); ty=mirrored(v*.78+index*9+0*xx,th)
        else:
            tx=mirrored(xx*.44+index*tw*.39+0*v,tw)
            ty=mirrored(v*.68+index*th*.43+(1-index)*th*.14+0*xx,th)
        surface=tex[ty,tx].astype(float)
        # Let the drawing set the local exposure without washing out the artist's motifs.
        mean=np.asarray(tex,dtype=float).mean(axis=(0,1))
        surface=np.clip(surface*.83 + (native-np.array(mean))*.52 + np.array(mean)*.17,0,255)
        bounds=smooth((xx-22)/48)*smooth((WIDTH-23-xx)/48)
        feather=smooth(v/13)*smooth((depth-1-v)/14)
        strength=(bounds*feather)[:,:,None]
        # Real edge rail texture is carried from an adjacent slice, not a flat fill.
        dist=np.minimum(v,depth-1-v)
        step=(np.sin(dist*.084)*3.2).astype(int)
        sample=a[(seam[None,:]+step).clip(0,SOURCE_HEIGHT-1),xx].astype(float)
        frame=edge*.61+sample*.39
        body[start[None,:]+v,xx]=np.uint8(np.clip(frame*(1-strength)+surface*strength,0,255))
    # Carry the outside sculpture as one continuous piece. In particular a
    # gearbox, blossom branch, speaker or glass valve must not be cut twice by
    # the new key rows. The worked centre ends before these outer castings.
    # Interpolate between original scan lines for grain and diagonal outlines.
    yy=np.arange(HEIGHT,dtype=float)
    for side in ("left","right"):
        if side=="left":
            weight=1-smooth((xx-286)/55)
            if name in ("steampunk","steampunk_ii","custom"):
                source=(0,530,596,600,604,607,838,865)
                dest=(0,530,596,633,772,851,1082,1109)
            else:
                source=(0,530,589,619,659,706,838,865)
                dest=(0,530,589,687,814,950,1082,1109)
        else:
            weight=smooth((xx-1579)/82)
            source=(0,530,544,606,730,803,838,865)
            dest=(0,530,544,667,891,1035,1082,1109)
            if name in ('steampunk','steampunk_ii','custom'):
                source=(0,530,545,558,581,601,838,865)
                dest=(0,530,545,637,775,845,1082,1109)
        yf=np.interp(yy,dest,source);lo=yf.astype(int);f=(yf-lo)[:,None,None]
        wing=a[lo]*(1-f)+a[np.minimum(lo+1,SOURCE_HEIGHT-1)]*f
        if side=="left" and name in ("steampunk","steampunk_ii","custom"):
            # The small empty casting beneath STOP is widened, keeping the
            # silhouette of the large wheel and the vertical rim undistorted.
            m=(smooth((yy-600)/35)*smooth((851-yy)/35))[:,None]
            m=m*smooth((xx-30)/48)*smooth((313-xx)/55)
            tx=mirrored(xx*.7+0*ys,tw); ty=mirrored((ys-596)*.72+0*xx,th)
            insert=tex[ty,tx].astype(float)
            wing=wing*(1-m[:,:,None]*.87)+insert*(m[:,:,None]*.87)
        body=np.uint8(np.clip(body*(1-weight[:,:,None])+wing*weight[:,:,None],0,255))
    if name in ("steampunk","steampunk_ii"):
        # Registered restoration portraits: the thin pipes, curled foliage and
        # corner fittings bridge the wider case at their natural proportions.
        row=0 if name=="steampunk" else 1
        with Image.open(DESIGN/"side_restorations.jpg") as atlas:
            for col,x0 in enumerate((0,WIDTH-500)):
                detail=np.asarray(atlas.crop((col*500,row*434,(col+1)*500,(row+1)*434)),dtype=float)
                u=np.arange(500)[None,:]+x0; v=np.arange(434)[:,None]+506
                if col==0:
                    fade=smooth((u-8)/22)*smooth((364-u)/45)*smooth((v-593)/32)*smooth((903-v)/46)
                else:
                    fade=smooth((u-1565)/46)*smooth((WIDTH-5-u)/16)*smooth((v-526)/34)*smooth((936-v)/46)
                patch=body[506:940,x0:x0+500]
                patch[:]=np.uint8(np.clip(patch*(1-fade[:,:,None])+detail*fade[:,:,None],0,255))
    return Image.fromarray(body)

def source_box(name, kind):
    special=name in ("steampunk","custom")
    if kind in ("run","stop"):
        if special:
            return (63,384,233,492) if kind=="run" else (63,494,233,600)
        if name=="steampunk_ii":
            return (62,388,221,484) if kind=="run" else (62,495,221,590)
        return (75,392,222,482) if kind=="run" else (75,497,222,587)
    if special:
        return (1005,428,1147,495) if kind=="neutral" else (1152,428,1303,495)
    if name=="steampunk_ii":
        return (1007,429,1136,491) if kind=="neutral" else (1171,429,1296,491)
    return (1011,435,1136,485) if kind=="neutral" else (1179,435,1289,485)

def mask_for(size, name, tall):
    w,h=size; z=3
    mask=Image.new("L",(w*z,h*z)); pen=ImageDraw.Draw(mask)
    # The silhouette is traced outside the fasteners. Each family keeps its own
    # shoulders and corner geometry; the voids show the local faceplate.
    if name in ("steampunk","custom"):
        rect=(1*z,1*z,(w-1)*z,(h-1)*z)
        pen.rounded_rectangle(rect,radius=(6 if tall else 5)*z,fill=255)
    else:
        if name in ("steampunk_ii","goa_trance"):
            pts=[(.00,.44),(.055,.32),(.072,.17),(.14,.105),(.19,.08),(.30,.075),(.38,.07),(.44,.035),(.5,0),(.56,.045),(.64,.075),(.82,.075),(.87,.095),(.935,.18),(.95,.34),(1,.43),(.987,.57),(.954,.63),(.925,.83),(.86,.90),(.74,.93),(.62,.94),(.52,.99),(.48,.99),(.39,.94),(.20,.93),(.13,.89),(.06,.80),(.044,.63),(.008,.56)]
        else:
            tip=.075 if name=="classic" else .105
            pts=[(0,.42),(.025,.35),(tip,.07),(tip+.055,.025),(1-tip-.045,.025),(1-tip,.07),(.98,.34),(1,.41),(1,.60),(.973,.67),(1-tip,.91),(1-tip-.05,.97),(tip+.04,.97),(tip,.93),(.026,.66),(0,.59)]
        pen.polygon([(round(u*(w*z-1)),round(v*(h*z-1))) for u,v in pts],fill=255)
    return mask.resize(size,AA)

def remove_engraving(crop, tall):
    # The label is the only material replaced. Reconstruct the worn field from
    # narrow samples to its left and right, retaining patina and vertical lighting.
    arr=np.asarray(crop.convert("RGB"),dtype=float)
    h,w=arr.shape[:2]
    x=np.linspace(0,1,w)[None,:]; y=np.linspace(0,1,h)[:,None]
    L,R=(.225,.779) if tall else (.195,.80)
    def band_at(frac):
        pos=round(w*frac)
        return np.median(arr[:,max(0,pos-2):pos+3],axis=1)[:,None,:]
    t=smooth((x-L)/(R-L))[:,:,None]
    replacement=(1-t)*band_at(L)+t*band_at(R)
    seed=arr[:,np.arange(w)%max(4,round(.037*w))+max(0,round(.17*w))].copy()
    detail=seed-np.median(seed,axis=1,keepdims=True)
    replacement+=detail*.31
    horizontal=smooth((x-(L-.028))/.054)*smooth(((R+.035)-x)/.06)
    vertical=(smooth((y-.105)/.065)*smooth((.83-y)/.068) if tall else
              smooth((y-.218)/.084)*smooth((.798-y)/.085))
    m=(horizontal*vertical)[:,:,None]
    return Image.fromarray(np.uint8(np.clip(arr*(1-m)+replacement*m,0,255)))

def fit_fitting(image,size):
    # Scale the height first. Only the centre can then change width: all four
    # corners and actual side bolts keep their aspect ratio.
    w,h=size
    r=h/image.height; nw=max(1,round(image.width*r))
    im=image.resize((nw,h),AA)
    end=min(max(5,round(nw*.215)),w//3,(nw-1)//2)
    result=Image.new(im.mode,size)
    result.paste(im.crop((0,0,end,h)),(0,0))
    result.paste(im.crop((nw-end,0,nw,h)),(w-end,0))
    result.paste(im.crop((end,0,nw-end,h)).resize((w-2*end,h),AA),(end,0))
    return result

def fitting(original,name,kind):
    side=original.crop(source_box(name,kind))
    tall=kind in ("stop","run")
    clean=remove_engraving(side,tall).convert("RGBA")
    clean.putalpha(mask_for(clean.size,name,tall))
    return clean

def glyph(drawable,x,y,which,r,ink):
    # Engraved transport-style arrow; draw it explicitly for identical lettering on all hosts.
    z=3; w=round(2*r+8); h=round(r+7)
    layer=Image.new("RGBA",(w*z,h*z)); d=ImageDraw.Draw(layer)
    def p(u,v):return (round(u*z),round(v*z))
    d.arc((4*z,4*z,(w-4)*z,(h+4)*z),192,352,fill=ink,width=2*z)
    d.polygon([p(1,6),p(8,1),p(7,10)],fill=ink)
    layer=layer.resize((w,h),AA)
    if which=="redo":layer=ImageOps.mirror(layer)
    drawable.paste(layer,(round(x-w/2),round(y-h/2)),layer)

def key_art(originals,key,name,state):
    x,y,X,Y=key.box; w,h=X-x,Y-y
    # Transport rocker casting on BACK and REDO; local articulation bezels
    # on the shorter keys, with the local paint selected for the action.
    kind=key.source
    finished=fit_fitting(originals[kind],(w-4,h-5))
    if not key.glyph and kind in ("stop","run"):
        finished=fit_fitting(originals["neutral"],(w-4,h-5))
        pixels=np.asarray(finished).copy(); H,W=pixels.shape[:2]
        yy,xx=np.mgrid[0:H,0:W]; u=xx/(W-1);v=yy/(H-1)
        field=(smooth((u-.18)/.09)*smooth((.83-u)/.09)*smooth((v-.22)/.14)*smooth((.79-v)/.14))[:,:,None]
        tint=np.array((.82,1.12,.82) if kind=="run" else (1.17,.84,.77))
        pixels[:,:,:3]=np.uint8(np.clip(pixels[:,:,:3]*(1+field*(tint-1)),0,255))
        finished=Image.fromarray(pixels)
    raw=np.asarray(finished).copy(); H,W=raw.shape[:2]; yy,xx=np.mgrid[:H,:W]
    u=xx/(W-1);v=yy/(H-1)
    field=(smooth((u-.115)/.11)*smooth((.89-u)/.11)*smooth((v-.155)/.13)*smooth((.85-v)/.14))[:,:,None]
    lamp=np.array(color(STYLE.get(name,STYLE["steampunk"])[3]))
    if state:
        pix=raw[:,:,:3].astype(float)
        if state==1:
            wash=(.145 if name!="classic" else .085)*field
            pix=pix*(1-wash)+lamp*wash
        else:
            pix=pix*(1-field*.23)
        raw[:,:,:3]=np.uint8(np.clip(pix,0,255))
    metal=Image.fromarray(raw)
    keyface=Image.new("RGBA",(w,h))
    # The ambient contact shadow falls outside the illustrated bezel, onto the
    # surrounding chassis. There is no rectangular group backing.
    shadow=Image.new("L",(w,h));shadow.paste(metal.getchannel("A"),(2,3))
    shadow=shadow.filter(ImageFilter.GaussianBlur(1.45)).point(lambda q:round(q*.86))
    keyface.paste((5,4,4,255),(0,0,w,h),shadow)
    keyface.alpha_composite(metal,(1,1))
    style=STYLE.get(name,STYLE["steampunk"]); ink=color(style[0])
    if name=="classic" and kind in ("stop","run"):ink=((111,34,30) if kind=="stop" else (24,78,48))
    if name=="cyberpunk" and (kind=="stop" or kind=="neutral"): ink=(255,191,236)
    family=legend_family(name)
    shade=(236,229,206) if name=="classic" else (27,15,12)
    dy=2 if state==2 else 0
    if key.glyph:
        glyph(keyface,w*.50,h*.32+dy,key.glyph,10,ink)
        letter(keyface,(w*.50,h*.59+dy),key.text,26,w*.67,ink,family,shade,h*.215)
    else:
        letter(keyface,(w*.50,h*.505+dy),key.text,24,w*.68,ink,family,shade,h*.34)
    # A little jewel sits in the lip, not on a separate on-screen rectangle.
    d=ImageDraw.Draw(keyface); cx,cy=round(w*.5),round(h*(.82 if key.glyph else .83))
    r=3 if h<=60 else 3.6
    d.ellipse((cx-r-1,cy-r,cx+r+1,cy+r+1),fill=(31,24,23),outline=(94,78,63))
    led=tuple(lamp.tolist()) if state else tuple(round(v*.23) for v in lamp)
    d.ellipse((cx-r+1,cy-r+1,cx+r-1,cy+r-1),fill=led)
    if state:d.point((cx,cy-1),fill=(255,253,221))
    return keyface

def lcd_art(body, original, shapes, name):
    x,y,X,Y=LCD; y+=SEAM; Y+=SEAM;w=X-x;h=Y-y
    if name in ("steampunk","custom"):
        frame=fit_fitting(shapes["blue"],(w,h))
        shadow=Image.new("RGBA",(w,h))
        shadow.alpha_composite(frame)
        d=ImageDraw.Draw(shadow)
        d.rounded_rectangle((15,7,w-15,h-8),radius=4,fill=(22,25,20),outline=(124,102,63),width=2)
        d.line((20,10,w-21,10),fill=(7,9,8),width=2)
        body.paste(shadow,(x,y),shadow)
    else:
        bezel=original.crop((852,698,1344,758)).convert("RGBA")
        bezel=fit_fitting(bezel,(w,h))
        alpha=Image.new("L",(w,h));ImageDraw.Draw(alpha).rounded_rectangle((0,0,w-1,h-1),radius=6,fill=255)
        body.paste(bezel,(x,y),alpha)

def engravings(body,name):
    style=STYLE.get(name,STYLE["steampunk"])
    fam=legend_family(name)
    shade=(234,230,220) if name=="classic" else (26,17,21)
    for xx,yy,width,val in ((677,19,150,"CURSOR"),(1000,15,290,"PATTERN MODE"),
                            (1400,15,320,"TIMING"),(507,224,390,"PATTERN WRITE"),
                            (980,224,380,"TRACK"),(1424,221,300,"MEMORY")):
        letter(body,(xx,SEAM+yy),val,15,width,color(style[1]),fam,shade)

def state_box(key,state):
    i=tuple(KEYS).index(key.id)+(state-1)*len(KEYS); col=i%COLS;row=i//COLS
    l,t,r,b=key.box; x=col*PACK_W; y=row*PACK_H
    return x,y,x+r-l,y+b-t

def build(original,name):
    body=extend_body(original,name)
    shapes={k:fitting(original,name,k) for k in ("stop","run","neutral","blue")}
    lcd_art(body,original,shapes,name);engravings(body,name)
    states=Image.new("RGB",PACK_SIZE)
    for key in KEYS.values():
        x,y,X,Y=key.box; y+=SEAM;Y+=SEAM
        ground=body.crop((x,y,X,Y))
        for state in (0,1,2):
            cap=key_art(shapes,key,name,state);tile=ground.copy();tile.paste(cap,(0,0),cap)
            if not state:body.paste(tile,(x,y))
            else:states.paste(tile,state_box(key,state)[:2])
    return body,states

def bake(name):
    with Image.open(source_path(name)) as src:
        canvas,states=build(src.convert("RGB"),name)
    target=ART/name;target.mkdir(parents=True,exist_ok=True)
    canvas.crop((0,FILM_TOP,WIDTH,FILM_END+BAY)).save(target/"inlay.png",compress_level=7)
    states.save(target/"switches.png",compress_level=7)

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skins",nargs="*",help="Skin IDs (default: all factory instruments)")
    args=parser.parse_args()
    for name in (args.skins or SKIN_NAMES):
        if name not in SKIN_NAMES:parser.error("Unknown skin: "+name)
        bake(name);print(name,flush=True)

