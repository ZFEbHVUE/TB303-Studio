"""Sound-reactive lights positioned in the themed instrument hardware."""

import math
from typing import NamedTuple

import tkinter as tk


class Lens(NamedTuple):
    x: float
    y: float
    width: float
    height: float
    shape: str
    color: str


class Style(NamedTuple):
    glow: str
    secondary: str
    peak: str
    dial_angles: tuple
    dial_shape: str
    key_shape: str
    meter_shape: str


STYLES = {
    "cyberpunk": Style("#58ecff", "#ff58b9", "#ff71ac", (163, 235, 320), "dash", "dash", "slot"),
    "hard_cyberpunk": Style("#ff9d39", "#ffc677", "#ff5148", (145, 215, 310), "slot", "slot", "slot"),
    "cyber_reggae": Style("#78ff73", "#ffd34e", "#ff5b4d", (157, 225, 300), "diamond", "slot", "diamond"),
    "goa_trance": Style("#78f9ee", "#e994ff", "#ff83c5", (150, 210, 270, 330), "diamond", "diamond", "diamond"),
    "trance_dub": Style("#71deff", "#9b9dff", "#f594ff", (158, 220, 320), "glass", "dash", "glass"),
    "dub": Style("#ffc268", "#ff9a54", "#ff644a", (155, 219), "glass", "glass", "glass"),
    "reggae": Style("#73e792", "#ffc254", "#ff684f", (150, 213, 325), "glass", "slot", "glass"),
    "steampunk_ii": Style("#ffc470", "#a1ffac", "#ff754a", (151, 226, 312), "glass", "glass", "glass"),
    "classic": Style("#fb5b4e", "#ff977b", "#ff4a40", (218, 322), "slot", "slot", "slot"),
    "acid_rave": Style("#d8fd43", "#ca74ff", "#ff7ed3", (150, 211, 325), "dash", "diamond", "slot"),
}
WHITE_KEYS = tuple(f"{note}{octave}" for octave in range(1, 4) for note in "CDEFGAB")
BLACK_OFFSETS = (0, 1, 3, 4, 5)
BLACK_KEYS = tuple(f"{'CDEFGAB'[index]}#{octave}" for octave in range(1, 4)
                   for index in BLACK_OFFSETS)


def lighting_lenses(layout, skin):
    """Native coordinates shared by the panel artwork and the live lights."""
    style = STYLES[skin]
    dials = []
    for cx, cy, radius, _, _ in layout["knobs"].values():
        for i, degrees in enumerate(style.dial_angles):
            angle = math.radians(degrees)
            r = radius + 3
            size = 9 if style.dial_shape == "diamond" else 7
            dials.append(Lens(cx + r * math.cos(angle), cy + r * math.sin(angle),
                              size + (3 if style.dial_shape == "dash" else 0), size - 2,
                              style.dial_shape, style.secondary if i % 2 else style.glow))
    left, top, right, bottom = layout["piano"]
    key_width = (right - left) / len(WHITE_KEYS)
    whites = [Lens(left + (i + .5) * key_width, bottom - 7, 12, 5, style.key_shape,
                   style.secondary if i % 3 == 2 else style.glow)
              for i in range(len(WHITE_KEYS))]
    blacks = [Lens(left + (white + octave * 7 + 1) * key_width, top + 79,
                   8, 5, style.key_shape, style.secondary)
              for octave in range(3) for white in BLACK_OFFSETS]
    buttons = []
    for name, (x, y, hw, hh) in layout["buttons"].items():
        w, h = (8, 10) if hh > 20 else (8, 7)
        for side in (-1, 1):
            color = style.peak if name in ("record", "stop") and side == 1 else style.secondary
            buttons.append(Lens(x + side * (hw + 11), y, w, h, style.dial_shape, color))
    cells = layout["cells"]
    steps = [Lens(x, cells["cy"] + cells["hh"] + 11, 16, 6, style.key_shape,
                  style.secondary if i % 4 == 3 else style.glow)
             for i, x in enumerate(cells["cx"])]
    meter = []
    for i in range(12):
        h = 14 if style.meter_shape in ("glass", "diamond") else 10 + i
        color = style.glow if i < 8 else style.secondary if i < 10 else style.peak
        meter.append(Lens(1386 + 19 * i, 111 - h / 3, 12, h, style.meter_shape, color))
    return {"dials": dials, "white": whites, "black": blacks,
            "buttons": buttons, "steps": steps, "meter": meter}


def draw_lens(draw, box, shape, fill):
    x0, y0, x1, y1 = box
    if shape == "glass":
        draw.ellipse(box, fill=fill)
    elif shape == "diamond":
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        draw.polygon(((x0, my), (mx, y0), (x1, my), (mx, y1)), fill=fill)
    elif shape == "dash":
        slant = min((x1 - x0) * .25, (y1 - y0) * .55)
        draw.polygon(((x0 + slant, y0), (x1, y0), (x1 - slant, y1), (x0, y1)), fill=fill)
    else:
        draw.rounded_rectangle(box, radius=min(x1 - x0, y1 - y0) * .23, fill=fill)


class SkinLights:
    """Small cached optical glows, drawn above the physical lenses."""

    LEVELS = 9

    def __init__(self, canvas, scale, layout, skin):
        self.canvas = canvas
        self.scale = scale
        self.peak = 0.0
        self._frames = {}
        self._items = {}
        self._last = {}
        for group, lenses in lighting_lenses(layout, skin).items():
            self._items[group] = [
                (lens, canvas.create_image(lens.x * scale, lens.y * scale, state=tk.HIDDEN))
                for lens in lenses
            ]
            self._last[group] = [-1] * len(lenses)

    def close(self):
        for placements in self._items.values():
            for _, item in placements:
                self.canvas.delete(item)
        self._frames.clear()

    def _photo(self, lens, level):
        from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageTk

        w = max(3, round(lens.width * self.scale))
        h = max(3, round(lens.height * self.scale))
        key = (w, h, lens.shape, lens.color, level)
        if key in self._frames:
            return self._frames[key]
        strength = level / self.LEVELS
        radius = max(2, round((max(w, h) * .48 + 4) * (.75 + .25 * strength)))
        size = (w + 2 * radius + 2, h + 2 * radius + 2)
        shape = Image.new("L", size)
        focus = (radius, radius, radius + w, radius + h)
        draw_lens(ImageDraw.Draw(shape), focus, lens.shape, 255)
        rgb = ImageColor.getrgb(lens.color)
        halo = Image.new("RGBA", size, (*rgb, 0))
        halo.putalpha(shape.filter(ImageFilter.GaussianBlur(max(1.4, radius * .60)))
                      .point(lambda value: min(255, round(value * strength * 1.75))))
        glass = Image.new("RGBA", size, (*rgb, 0))
        glass.putalpha(shape.point(lambda value: round(value * strength * .94)))
        glow = Image.alpha_composite(halo, glass)
        if level >= 5:
            spec = ImageDraw.Draw(glow)
            light = tuple(round(c + (255 - c) * .53) for c in rgb)
            spec.line((radius + w * .28, radius + h * .34,
                       radius + w * .70, radius + h * .34),
                      fill=(*light, round(180 * strength)), width=1)
        photo = ImageTk.PhotoImage(glow, master=self.canvas)
        self._frames[key] = photo
        return photo

    def _set(self, group, levels):
        last = self._last[group]
        for i, ((lens, item), amount) in enumerate(zip(self._items[group], levels)):
            value = round(max(0.0, min(1.0, amount)) * self.LEVELS)
            if last[i] == value:
                continue
            last[i] = value
            if value == 0:
                self.canvas.itemconfigure(item, state=tk.HIDDEN)
            else:
                self.canvas.itemconfigure(item, state=tk.NORMAL, image=self._photo(lens, value))

    def show(self, level, step=None, note=None):
        """Follow the output amplitude, play position, and last auditioned note."""
        level = max(0.0, min(1.0, level))
        strength = level ** .72
        self.peak = max(level, self.peak - .045) if level or step is not None else 0.0
        crest = min(11, int(self.peak * 12)) if self.peak > .035 else -1
        self._set("meter", (max(.66 if i == crest else 0.0, min(1.0, strength * 12 - i))
                            for i in range(12)))
        self._set("dials", (strength * (.52 + .41 * (i % 3) / 2)
                            for i in range(len(self._items["dials"]))))
        self._set("buttons", (min(1.0, strength * (1.04 if i % 4 == 1 else .72))
                              for i in range(len(self._items["buttons"]))))
        self._set("white", (max(.90 if key == note else 0.0,
                                strength * (.67 if i % 3 != 1 else .42))
                             for i, key in enumerate(WHITE_KEYS)))
        self._set("black", (max(.90 if key == note else 0.0, strength * .65) for key in BLACK_KEYS))
        self._set("steps", (min(1.0, .34 + .65 * strength) if i == step else 0.0
                            for i in range(len(self._items["steps"]))))
