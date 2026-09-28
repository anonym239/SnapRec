"""Farben, Schriften, Logo, Icons und kleine Animations-Helfer."""

import math
import sys
import time
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFont

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# ---- Farben (dunkles, modernes Design) -----------------------------------
BG = "#0e1014"
SURFACE = "#171a21"
SURFACE_2 = "#20242d"
SURFACE_3 = "#2a2f3a"
BORDER = "#2b303b"
TEXT = "#f3f4f7"
MUTED = "#8a91a3"
ACCENT = "#7c5cff"
ACCENT_HOVER = "#6b4bf0"
ACCENT_2 = "#ff4d8d"
REC = "#ff3b5c"
REC_HOVER = "#e22d4d"
PAUSE = "#ffb020"
OK = "#2fd184"

# Tk-Schriftfamilie – wird beim Start mit init_fonts() festgelegt
FONT = "Segoe UI"
MONO = "Consolas"


def init_fonts(root):
    """Beste verfügbare Schrift wählen."""
    global FONT, MONO
    import tkinter.font as tkfont
    families = set(tkfont.families(root))
    for name in ("Segoe UI Variable Text", "Segoe UI", "Inter", "SF Pro Text",
                 "Helvetica Neue", "Ubuntu", "Cantarell", "DejaVu Sans"):
        if name in families:
            FONT = name
            break
    for name in ("Cascadia Mono", "Consolas", "SF Mono", "JetBrains Mono",
                 "Ubuntu Mono", "DejaVu Sans Mono"):
        if name in families:
            MONO = name
            break


# ---- Farb- und Animations-Helfer -----------------------------------------

def hex_to_rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in rgb[:3])


def mix(c1, c2, t):
    a, b = hex_to_rgb(c1), hex_to_rgb(c2)
    return rgb_to_hex(tuple(x + (y - x) * t for x, y in zip(a, b)))


def rgba(color, alpha=255):
    return hex_to_rgb(color) + (int(alpha),)


def clamp01(t):
    return 0.0 if t < 0 else 1.0 if t > 1 else t


def ease_out_cubic(t):
    t = clamp01(t)
    return 1 - (1 - t) ** 3


def ease_in_out(t):
    t = clamp01(t)
    return t * t * (3 - 2 * t)


def ease_out_back(t, s=1.70158):
    t = clamp01(t) - 1
    return t * t * ((s + 1) * t + s) + 1


def animate(widget, duration_ms, step, done=None, ease=ease_out_cubic):
    """step(fortschritt 0..1) ca. 60× pro Sekunde aufrufen."""
    start = time.perf_counter()

    def tick():
        try:
            if not widget.winfo_exists():
                return
        except Exception:
            return
        t = min(1.0, (time.perf_counter() - start) * 1000 / duration_ms)
        step(ease(t))
        if t < 1:
            widget.after(16, tick)
        elif done:
            done()

    tick()


# ---- PIL-Schriften -------------------------------------------------------

_FONT_FILES = {
    "regular": ["segoeui.ttf", "Inter-Regular.otf", "Inter-Regular.ttf",
                "/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc",
                "DejaVuSans.ttf"],
    "semibold": ["seguisb.ttf", "Inter-SemiBold.otf", "Inter-SemiBold.ttf",
                 "/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc",
                 "DejaVuSans-Bold.ttf"],
    "bold": ["segoeuib.ttf", "Inter-Bold.otf", "Inter-Bold.ttf",
             "/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc",
             "DejaVuSans-Bold.ttf"],
    "mono": ["CascadiaMono.ttf", "consola.ttf", "/System/Library/Fonts/Menlo.ttc",
             "DejaVuSansMono.ttf"],
}


@lru_cache(maxsize=None)
def pil_font(size, weight="regular"):
    size = max(1, int(size))
    for name in _FONT_FILES[weight]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


# ---- Bilder: Verlauf, Logo, Icons ----------------------------------------

@lru_cache(maxsize=32)
def gradient(size, c1=ACCENT, c2=ACCENT_2):
    """Diagonaler Farbverlauf (oben links c1 → unten rechts c2)."""
    w, h = size
    vertical = Image.linear_gradient("L").resize((w, h))
    horizontal = Image.linear_gradient("L").rotate(90).transpose(
        Image.Transpose.FLIP_LEFT_RIGHT).resize((w, h))
    mask = ImageChops.add(vertical, horizontal, scale=2.0)
    return Image.composite(Image.new("RGB", (w, h), c2), Image.new("RGB", (w, h), c1), mask)


def draw_brackets(draw, box, length, width, fill):
    """Vier Ecken-Winkel wie beim Snipping Tool/Logo."""
    x1, y1, x2, y2 = box
    for cx, cy, dx, dy in ((x1, y1, 1, 1), (x2, y1, -1, 1), (x1, y2, 1, -1), (x2, y2, -1, -1)):
        draw.line([(cx, cy + dy * length), (cx, cy), (cx + dx * length, cy)],
                  fill=fill, width=width, joint="curve")
        r = width / 2
        for px, py in ((cx, cy + dy * length), (cx + dx * length, cy)):
            draw.ellipse((px - r, py - r, px + r, py + r), fill=fill)


@lru_cache(maxsize=32)
def logo_image(size):
    """App-Logo: Verlaufs-Quadrat mit Auswahl-Ecken und Aufnahme-Punkt."""
    s = size * 4
    grad = gradient((s, s)).convert("RGBA")
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.27), fill=255)
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    m = s * 0.24
    draw_brackets(d, (m, m, s - m, s - m), s * 0.15, max(2, int(s * 0.065)), (255, 255, 255, 255))
    c, r = s / 2, s * 0.12
    d.ellipse((c - r, c - r, c + r, c + r), fill=(255, 255, 255, 255))
    return img.resize((size, size), Image.Resampling.LANCZOS)


@lru_cache(maxsize=128)
def icon_image(name, size=64, color=TEXT):
    """Einfache, scharfe Icons (ohne Emoji-Schriften)."""
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fill = rgba(color)
    w = max(2, int(s * 0.09))
    if name == "record":
        r = s * 0.26
        d.ellipse((s / 2 - r, s / 2 - r, s / 2 + r, s / 2 + r), fill=fill)
    elif name == "stop":
        a = s * 0.27
        d.rounded_rectangle((s / 2 - a, s / 2 - a, s / 2 + a, s / 2 + a), radius=s * 0.07, fill=fill)
    elif name == "pause":
        bw, bh = s * 0.13, s * 0.27
        for cx in (s * 0.37, s * 0.63):
            d.rounded_rectangle((cx - bw / 2, s / 2 - bh, cx + bw / 2, s / 2 + bh), radius=s * 0.04, fill=fill)
    elif name == "play":
        d.polygon([(s * 0.34, s * 0.24), (s * 0.34, s * 0.76), (s * 0.78, s * 0.5)], fill=fill)
    elif name == "fullscreen":
        draw_brackets(d, (s * 0.2, s * 0.2, s * 0.8, s * 0.8), s * 0.2, w, fill)
    elif name == "select":
        draw_brackets(d, (s * 0.18, s * 0.22, s * 0.82, s * 0.78), s * 0.17, w, fill)
        r = s * 0.1
        d.ellipse((s / 2 - r, s / 2 - r, s / 2 + r, s / 2 + r), fill=fill)
    elif name == "folder":
        d.rounded_rectangle((s * 0.12, s * 0.22, s * 0.5, s * 0.42), radius=s * 0.06, fill=fill)
        d.rounded_rectangle((s * 0.12, s * 0.3, s * 0.88, s * 0.8), radius=s * 0.08, fill=fill)
    elif name == "gear":
        c = s / 2
        for i in range(8):
            a = i * math.pi / 4
            x, y = c + math.cos(a) * s * 0.33, c + math.sin(a) * s * 0.33
            d.ellipse((x - s * 0.08, y - s * 0.08, x + s * 0.08, y + s * 0.08), fill=fill)
        d.ellipse((c - s * 0.3, c - s * 0.3, c + s * 0.3, c + s * 0.3), fill=fill)
        d.ellipse((c - s * 0.12, c - s * 0.12, c + s * 0.12, c + s * 0.12), fill=(0, 0, 0, 0))
    elif name == "help":
        c = s / 2
        d.ellipse((s * 0.12, s * 0.12, s * 0.88, s * 0.88), outline=fill, width=w)
        f = pil_font(int(s * 0.5), "bold")
        d.text((c, c + s * 0.02), "?", font=f, fill=fill, anchor="mm")
    elif name == "check_circle":
        d.ellipse((0, 0, s - 1, s - 1), fill=rgba(OK))
        d.line([(s * 0.28, s * 0.52), (s * 0.44, s * 0.67), (s * 0.73, s * 0.37)],
               fill=(255, 255, 255, 255), width=int(w * 1.2), joint="curve")
    elif name == "check":
        d.line([(s * 0.26, s * 0.52), (s * 0.43, s * 0.68), (s * 0.75, s * 0.34)],
               fill=fill, width=int(w * 1.3), joint="curve")
    elif name == "keyboard":
        d.rounded_rectangle((s * 0.08, s * 0.26, s * 0.92, s * 0.74), radius=s * 0.1,
                            outline=fill, width=w)
        for row, y in enumerate((0.4, 0.52)):
            for i in range(5):
                x = s * (0.22 + i * 0.14)
                d.rectangle((x - s * 0.03, s * y - s * 0.03, x + s * 0.03, s * y + s * 0.03), fill=fill)
        d.rectangle((s * 0.3, s * 0.6, s * 0.7, s * 0.65), fill=fill)
    elif name == "trash":
        d.rounded_rectangle((s * 0.22, s * 0.2, s * 0.78, s * 0.28), radius=s * 0.03, fill=fill)
        d.rounded_rectangle((s * 0.4, s * 0.12, s * 0.6, s * 0.22), radius=s * 0.03, fill=fill)
        d.polygon([(s * 0.27, s * 0.33), (s * 0.73, s * 0.33), (s * 0.68, s * 0.88), (s * 0.32, s * 0.88)],
                  fill=fill)
        for x in (0.42, 0.58):
            d.line([(s * x, s * 0.43), (s * x, s * 0.78)], fill=(0, 0, 0, 0), width=max(1, w // 2))
    elif name == "film":
        d.rounded_rectangle((s * 0.1, s * 0.22, s * 0.68, s * 0.78), radius=s * 0.1, fill=fill)
        d.polygon([(s * 0.72, s * 0.5), (s * 0.92, s * 0.3), (s * 0.92, s * 0.7)], fill=fill)
    elif name == "speaker":
        d.polygon([(s * 0.12, s * 0.38), (s * 0.3, s * 0.38), (s * 0.52, s * 0.18), (s * 0.52, s * 0.82),
                   (s * 0.3, s * 0.62), (s * 0.12, s * 0.62)], fill=fill)
        d.arc((s * 0.42, s * 0.3, s * 0.72, s * 0.7), -50, 50, fill=fill, width=w)
        d.arc((s * 0.42, s * 0.14, s * 0.9, s * 0.86), -50, 50, fill=fill, width=w)
    elif name == "mic":
        d.rounded_rectangle((s * 0.36, s * 0.1, s * 0.64, s * 0.6), radius=s * 0.14, fill=fill)
        d.arc((s * 0.24, s * 0.3, s * 0.76, s * 0.72), 0, 180, fill=fill, width=w)
        d.line([(s * 0.5, s * 0.72), (s * 0.5, s * 0.86)], fill=fill, width=w)
        d.line([(s * 0.34, s * 0.88), (s * 0.66, s * 0.88)], fill=fill, width=w)
    elif name == "close":
        d.line([(s * 0.3, s * 0.3), (s * 0.7, s * 0.7)], fill=fill, width=w)
        d.line([(s * 0.7, s * 0.3), (s * 0.3, s * 0.7)], fill=fill, width=w)
    return img.resize((size, size), Image.Resampling.LANCZOS)


def ctk_icon(name, size=18, color=TEXT):
    import customtkinter as ctk
    img = icon_image(name, size * 4, color)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))


# ---- Countdown-Anzeige (für Overlay und Einführung) ----------------------

def countdown_badge(size, number, frac, label="Esc = Abbrechen"):
    """Runder Countdown mit Verlaufs-Ring.

    number: angezeigte Zahl, frac: 0..1 Fortschritt innerhalb der Sekunde.
    Gibt ein RGBA-Bild zurück (Kantenglättung durch Supersampling).
    """
    k = 2
    s = size * k
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, s - 1, s - 1), fill=(14, 16, 20, 235))

    ring_w = max(4, int(s * 0.045))
    inset = int(s * 0.07)
    box = (inset, inset, s - inset, s - inset)
    d.ellipse(box, outline=(255, 255, 255, 38), width=ring_w)

    remaining = 1 - clamp01(frac)
    if remaining > 0.002:
        start = -90
        end = -90 + 360 * remaining
        mask = Image.new("L", (s, s), 0)
        md = ImageDraw.Draw(mask)
        md.arc(box, start, end, fill=255, width=ring_w)
        c = s / 2
        rad = (s - 2 * inset) / 2 - ring_w / 2
        for ang in (start, end):  # runde Enden
            x = c + math.cos(math.radians(ang)) * rad
            y = c + math.sin(math.radians(ang)) * rad
            md.ellipse((x - ring_w / 2, y - ring_w / 2, x + ring_w / 2, y + ring_w / 2), fill=255)
        img.paste(gradient((s, s)).convert("RGBA"), (0, 0), mask)

    # Zahl "springt" am Anfang jeder Sekunde leicht auf
    pop = ease_out_back(frac * 3.5)
    scale = 0.6 + 0.4 * pop
    alpha = int(255 * clamp01(frac * 6))
    f = pil_font(int(s * 0.42 * scale), "bold")
    d.text((s / 2, s * 0.47), str(number), font=f, fill=(255, 255, 255, alpha), anchor="mm")
    if label:
        d.text((s / 2, s * 0.76), label, font=pil_font(int(s * 0.065), "regular"),
               fill=(255, 255, 255, 140), anchor="mm")
    return img.resize((size, size), Image.Resampling.LANCZOS)


def pill(text, height, fg=TEXT, bg=SURFACE, border=BORDER, weight="semibold", pad=None,
         icon=None):
    """Abgerundetes 'Pillen'-Label als RGBA-Bild."""
    k = 2
    h = height * k
    f = pil_font(int(h * 0.42), weight)
    tw = int(f.getlength(text))
    pad = int((pad if pad is not None else height * 0.55) * k)
    icon_w = int(h * 0.5) + int(h * 0.25) if icon else 0
    w = tw + 2 * pad + icon_w
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=rgba(bg, 235),
                        outline=rgba(border) if border else None, width=k)
    x = pad
    if icon:
        ic = icon_image(icon, int(h * 0.5), fg)
        img.alpha_composite(ic, (x, (h - ic.height) // 2))
        x += icon_w
    d.text((x, h / 2), text, font=f, fill=rgba(fg), anchor="lm")
    return img.resize((w // k, height), Image.Resampling.LANCZOS)


def keycaps(parts, height=26, fg=TEXT, cap=SURFACE_3, edge="#3a4150"):
    """Tastenkombination als kleine Tasten-Bilder: [Strg] + [Alt] + [R]."""
    k = 3
    h = height * k
    f = pil_font(int(h * 0.44), "semibold")
    plus = pil_font(int(h * 0.44), "regular")
    gap = int(h * 0.22)
    widths = [max(h, int(f.getlength(p)) + int(h * 0.7)) for p in parts]
    plus_w = int(plus.getlength("+")) + 2 * gap
    w = sum(widths) + plus_w * (len(parts) - 1)
    img = Image.new("RGBA", (max(1, w), h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x = 0
    for i, (p, pw) in enumerate(zip(parts, widths)):
        d.rounded_rectangle((x, 0, x + pw - 1, h - 1), radius=int(h * 0.26), fill=rgba(edge))
        d.rounded_rectangle((x, 0, x + pw - 1, h - 1 - int(h * 0.1)), radius=int(h * 0.26), fill=rgba(cap))
        d.text((x + pw / 2, (h - h * 0.1) / 2), p, font=f, fill=rgba(fg), anchor="mm")
        x += pw
        if i < len(parts) - 1:
            d.text((x + plus_w / 2, h / 2), "+", font=plus, fill=rgba(MUTED), anchor="mm")
            x += plus_w
    return img.resize((max(1, w // k), height), Image.Resampling.LANCZOS)
