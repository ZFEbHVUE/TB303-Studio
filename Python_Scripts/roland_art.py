"""Animate only photographed moving parts. No synthetic pointer is drawn over a knob."""
from collections import OrderedDict
import math
import numpy as np
from PIL import Image
from roland_geometry import ROTORS, KEYS, LEDS

def smooth(x):
    x=np.clip(x,0,1)
    return x*x*(3-2*x)

def bilinear(a,x,y):
    x=np.clip(x,0,a.shape[1]-1.001);y=np.clip(y,0,a.shape[0]-1.001)
    i=x.astype(int);j=y.astype(int);u=(x-i)[...,None];v=(y-j)[...,None]
    return (a[j,i]*(1-u)+a[j,i+1]*u)*(1-v)+(a[j+1,i]*(1-u)+a[j+1,i+1]*u)*v

def rgb(a):
    return Image.fromarray(np.uint8(np.clip(np.rint(a),0,255)))

class PhotoRotor:
    def __init__(self,photo,k):
        bx,by,rx,ry=k.base;tx,ty,ux,uy=k.cap
        self.box=(math.floor(bx-rx)-2,math.floor(by-ry)-2,
                  math.ceil(bx+rx)+3,math.ceil(by+ry)+3)
        self.original=photo.crop(self.box);self.data=np.asarray(self.original,dtype=np.float32)
        x0,y0=self.box[:2];bx-=x0;by-=y0;tx-=x0;ty-=y0
        h,w=self.data.shape[:2];y,x=np.mgrid[:h,:w]
        # Nested eccentric ellipses register the elevated cap, its fluted skirt
        # and the base independently. A plain square crop would rotate the case.
        inside=((x-tx)/ux)**2+((y-ty)/uy)**2<=1
        lo=np.zeros((h,w));hi=np.ones((h,w))
        for _ in range(13):
            k0=(lo+hi)*.5
            error=((x-(tx+k0*(bx-tx)))/(ux+k0*(rx-ux)))**2+((y-(ty+k0*(by-ty)))/(uy+k0*(ry-uy)))**2
            lo=np.where(error>1,k0,lo);hi=np.where(error>1,hi,k0)
        tt=np.where(inside,0,(lo+hi)*.5)
        self.mx=tx+tt*(bx-tx);self.my=ty+tt*(by-ty)
        self.rx=ux+tt*(rx-ux);self.ry=uy+tt*(ry-uy)
        self.u=(x-self.mx)/self.rx;self.v=(y-self.my)/self.ry
        radius=np.sqrt(((x-bx)/rx)**2+((y-by)/ry)**2)
        self.alpha=smooth((1-radius)*min(rx,ry)/1.35)[...,None]
        self.ref=k.reference
        # Keep a fixed diffuse light on the barrel, while the photographed
        # index, facets and ridges are free to turn with the control.
        self.barrel=(tt*(1-tt)*1.4*(0 if k.selector else 1))[...,None]
        self.mean=self.ringlight(self.u,self.v)

    def sample(self,u,v):
        return bilinear(self.data,self.mx+u*self.rx,self.my+v*self.ry)

    def ringlight(self,u,v):
        acc=0.
        for deg in (-53,-35,-17,0,17,35,53):
            c=math.cos(math.radians(deg));s=math.sin(math.radians(deg))
            v0=self.sample(u*c-v*s,u*s+v*c)
            acc+=v0@np.array([.299,.587,.114])
        return acc/7.

    def frame(self,angle):
        # At the photographed position even the moving region is byte-for-byte original.
        delta=math.radians(self.ref-angle)
        if abs(delta)<1e-8:return self.original
        c,s=math.cos(delta),math.sin(delta)
        u=self.u*c-self.v*s;v=self.u*s+self.v*c
        warped=self.sample(u,v)
        if self.barrel.any():
            warped=warped+self.barrel*(self.mean-self.ringlight(u,v))[...,None]
        return rgb(self.data+(warped-self.data)*self.alpha)

class PhotoParts:
    def __init__(self,source):
        self.source=source
        self.rotors={n:PhotoRotor(source,q) for n,q in ROTORS.items()}
        self.lenses={n:self.lens(*p) for n,p in LEDS.items()}
        self.keys={n:self.depress(p) for n,p in KEYS.items()}

    def lens(self,cx,cy,r):
        m=math.ceil(r+5);box=(int(cx)-m,int(cy)-m,int(cx)+m+1,int(cy)+m+1)
        p=np.asarray(self.source.crop(box),dtype=float);y,x=np.mgrid[:p.shape[0],:p.shape[1]]
        u=(x+box[0]-cx)/r;v=(y+box[1]-cy)/r
        rr=np.hypot(u,v)
        # The lit core is inside the original glass. Retain its directional
        # reflection and a small spill on the immediately adjacent bezel.
        core=smooth((1.0-rr)/.30); glow=np.exp(-rr**2*2.4)*.57
        hot=np.exp(-((u+.10)**2+(v-.05)**2)/.28)
        emission=np.stack((np.clip(.86*core+glow,0,.99),
                           .09*core+.47*hot+.015*glow,.065*core+.24*hot),axis=-1)
        fade=smooth((1.60-rr)/.35)[...,None]
        return box,rgb(p+(255-p)*emission*fade)

    def depress(self,box):
        l,t,r,b=box
        src=np.asarray(self.source.crop(box),dtype=float);h,w=src.shape[:2];y,x=np.mgrid[:h,:w]
        depth=2.5 if h>44 else 1.6
        border=np.minimum(np.minimum(x,w-1-x),np.minimum(y,h-1-y))
        m=smooth((border-1)/3.2)[...,None]
        shadow=1-.20*np.exp(-np.maximum(y-3,0)/6)-.087
        moved=bilinear(src,x,y-depth)*shadow[...,None]
        return box,rgb(src*(1-m)+m*moved)

class TileCache(OrderedDict):
    """Keep only a bounded number of scaled Tk images; never cache a whole animation."""
    def get_or_create(self,key,make):
        if key not in self:
            self[key]=make()
            if len(self)>96:self.popitem(last=False)
        self.move_to_end(key)
        return self[key]
