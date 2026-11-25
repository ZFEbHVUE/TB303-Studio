"""Faceplate typography and fittings for the three integral value selectors."""
from PIL import Image, ImageDraw, ImageOps
from build_face_skins import STYLE, font, legend_family, color

# Enamel, frame, bright edge and shadow of each existing instrument.
FINISH = {
    "steampunk":      ("261c11","835b2c","c89b53","170f09"),
    "steampunk_ii":   ("102d28","94723e","d2b56b","0b1612"),
    "classic":        ("253439","626e70","c2c6bf","192328"),
    "acid_rave":      ("161a16","626b30","c2dd59","0b1011"),
    "cyberpunk":      ("0b192c","375a82","71c6db","080f1e"),
    "hard_cyberpunk": ("242221","776345","c79555","131516"),
    "goa_trance":     ("24142f","694471","c693ba","170d21"),
    "trance_dub":     ("141d36","435683","91b1ed","0b1225"),
    "dub":            ("2e251b","836648","c7a375","191711"),
    "reggae":         ("172b1b","736739","d7b96c","0e1912"),
    "cyber_reggae":   ("102a20","3a7158","a2cb82","0a1913"),
}
def blend(a,b,amount):
    return tuple(round(x+(y-x)*amount) for x,y in zip(a,b))

class Lettering:
    def __init__(self,skin,scale):
        self.skin=skin
        self.family=legend_family(skin)
        self.ink=color(STYLE.get(skin,STYLE["steampunk"])[2])
        self.glint=color(STYLE.get(skin,STYLE["steampunk"])[3])
        self.field,self.rim,self.edge,self.shade=map(color,FINISH.get(skin,FINISH["steampunk"]))
        self.size=max(10,round(18*scale))
        # Tk scales positions, not glyphs. Use the exact bundled face used on
        # the keys both here and in the drawer, regardless of desktop fonts.
        self.scale=scale

    def width(self,text):
        return font(self.size,self.family).getlength(text)

    def text(self,surface,value,x,centre,width,ink=None):
        size=self.size
        while size>8 and font(size,self.family).getlength(value)>width:
            size-=1
        typeface=font(size,self.family)
        d=ImageDraw.Draw(surface)
        # Keep a shared baseline for letters, fractions and triplet suffixes.
        top,bottom=typeface.getbbox("Ag")[1::2]
        y=round(centre-(bottom-top)/2-top)
        if self.scale>=.64:
            d.text((x+1,y+1),value,font=typeface,fill=self.shade)
        d.text((x,y),value,font=typeface,fill=ink or self.ink)

def field_picture(patch,style,value,keyboard,opened):
    im=patch.copy(); d=ImageDraw.Draw(im);w,h=im.size;sc=style.scale
    left=max(3,round(7*sc));arrow=max(5,round(10*sc))
    native=style.skin in ("steampunk","custom")
    # The original brass triangle on Steampunk is already in the photographed
    # socket. Other cases have a blank window and need a small engraved index.
    ax=w-max(4,round((11 if native else 10)*sc)); ay=h//2
    if not native:
        z=max(2,round(4.2*sc));sign=-1 if opened else 1
        ink=style.glint if keyboard or opened else blend(style.ink,style.field,.24)
        d.polygon([(ax-z,ay-sign*z//2),(ax+z,ay-sign*z//2),(ax,ay+sign*z//2+sign)],fill=ink)
    if keyboard and not opened:
        # Two tiny reflections flank the arrow for keyboard navigation only.
        c=style.glint;q=max(1,round(2*sc));span=max(4,round(7*sc))
        for xx,sign in ((ax-span,-1),(ax+span,1)):
            d.line((xx-sign*q,ay+q,xx,ay,xx-sign*q,ay-q),fill=c,width=1)
    style.text(im,value,left,h/2,max(1,w-left-arrow-max(6,round(14*sc))))
    return im

def chamfer(box,n):
    x,y,X,Y=box
    return ((x+n,y),(X-n,y),(X,y+n),(X,Y-n),(X-n,Y),(x+n,Y),(x,Y-n),(x,y+n))

def bevel(d,box,n,light,dark):
    pts=chamfer(box,n)
    d.line([pts[6],pts[7],pts[0],pts[1],pts[2]],fill=light,width=1)
    d.line([pts[2],pts[3],pts[4],pts[5],pts[6]],fill=dark,width=1)

class DrawerArt:
    """A recessed enamel tray, with grain sampled from the field's actual case."""
    def __init__(self,patch,material,style,row,margin,values):
        self.style=style;self.row=row;self.margin=margin;self.values=values
        self.base=patch.copy()
        w,h=patch.size;sc=style.scale
        p=max(2,round(3*sc));q=max(2,round(5*sc)); self.inset=p+2
        d=ImageDraw.Draw(self.base)
        shadow=chamfer((1,2,w-1,h-1),q)
        d.polygon(shadow,fill=blend(style.shade,(0,0,0),.40))
        d.polygon(chamfer((0,0,w-2,h-2),q),fill=style.rim)
        bevel(d,(0,0,w-2,h-2),q,style.edge,style.shade)
        d.polygon(chamfer((p,p,w-p-2,h-p-2),max(1,q-p)),fill=style.field)
        ww,hh=w-2*p-3,h-2*p-3
        # Stretch the native unlettered material, not the panel label or arrows.
        tex=ImageOps.grayscale(ImageOps.fit(material,(ww,hh),method=Image.Resampling.BILINEAR))
        tex=ImageOps.autocontrast(tex,cutoff=2)
        low=blend(style.field,style.shade,.44);high=blend(style.field,style.rim,.17)
        mine=ImageOps.colorize(tex,low,high)
        self.base.paste(mine,(p+1,p+1))
        bevel(d,(p,p,w-p-2,h-p-2),max(1,q-p),style.shade,blend(style.rim,style.shade,.47))
        if style.skin in ("steampunk","steampunk_ii","dub","custom") and sc>=.60:
            for u in (p+3,w-p-5):
                for v in (p+2,h-p-5):
                    d.ellipse((u-1,v-1,u+1,v+1),fill=style.shade)
                    d.point((u,v-1),fill=style.edge)
        # Separators are etched into the metal and are intentionally quiet.
        for i in range(1,len(values)):
            y=margin+i*row-1
            d.line((self.inset+3,y,w-self.inset-5,y),fill=blend(style.field,style.rim,.18))

    def picture(self,selected,active):
        im=self.base.copy();d=ImageDraw.Draw(im);w,h=im.size
        s=self.style;sc=s.scale
        g=max(7,round(13*sc));tx=self.inset+g+max(4,round(7*sc))
        for i,value in enumerate(self.values):
            top=self.margin+i*self.row;bot=top+self.row-2;cy=round((top+bot)/2)
            if i==active:
                left=self.inset;right=w-self.inset-2
                box=(left,top,right,bot)
                # Leave the colour variation of the enamel visible through the highlight.
                points=chamfer(box,max(1,round(3*sc)))
                mask=Image.new("L",im.size);ImageDraw.Draw(mask).polygon(points,fill=91)
                im.paste(s.rim,(0,0,w,h),mask)
                d.line((left+2,top,right-3,top),fill=blend(s.rim,s.field,.30))
                d.line((left+2,bot,right-3,bot),fill=s.shade)
            # The diamond marks the committed value. The light track can move
            # independently on hover or with the arrows, without editing the synth.
            if i==selected:
                cx=self.inset+round(g*.73);r=max(2,round(3.3*sc))
                d.polygon(((cx,cy-r),(cx+r,cy),(cx,cy+r),(cx-r,cy)),fill=s.glint)
                d.point((cx,cy-max(0,r-1)),fill=blend(s.glint,(255,255,239),.65))
            ink=blend(s.ink,(255,255,232),.12) if i==active else s.ink
            s.text(im,value,tx,cy,w-tx-self.inset-3,ink)
        return im
