"""Animierte Einführung – im Programm und als GIF für das README.

Alle Szenen werden mit Pillow gezeichnet (kantengeglättet), dadurch sehen sie
im Fenster und im exportierten GIF identisch aus.
"""

import math
import time
from functools import lru_cache

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from snaprec import theme
from snaprec.theme import clamp01, ease_in_out, ease_out_back, ease_out_cubic, rgba

W, H = 600, 400
SCREEN = (90, 18, 510, 254)          # Bildschirm im Monitor-Mockup
REGION = (50, 34, 290, 166)          # Auswahl relativ zum Bildschirm

SCENES = [
    ("Willkommen bei SnapRec",
     "Nimm jeden Bereich deines Bildschirms als Video auf –\nso einfach wie mit dem Snipping Tool.", 3.2),
    ("1  ·  Bereich aufziehen",
     "Der Bildschirm wird grau. Zieh mit der Maus den Bereich auf –\nDoppelklick nimmt den ganzen Monitor.", 3.8),
    ("2  ·  Countdown",
     "Nach 3, 5 oder 10 Sekunden geht’s los – genug Zeit,\num alles vorzubereiten. Esc bricht ab.", 4.0),
    ("3  ·  Aufnehmen & speichern",
     "Pause und Stopp über die kleine Leiste oder dein eigenes\nTastenkürzel. Gespeichert wird in 1080p – auf Wunsch mit Ton.", 4.8),
]
TRANSITION = 0.38


class Painter:
    """Zeichnet in Basis-Koordinaten (600×400) mit Skalierungsfaktor k."""

    def __init__(self, img, k):
        self.img, self.k = img, k
        self.d = ImageDraw.Draw(img)

    def s(self, *v):
        flat = []

        def add(x):
            if isinstance(x, (tuple, list)):
                for y in x:
                    add(y)
            else:
                flat.append(x * self.k)
        add(v)
        return flat

    def rect(self, box, r=0, fill=None, outline=None, width=1):
        self.d.rounded_rectangle(self.s(*box), radius=r * self.k, fill=fill, outline=outline,
                                 width=max(1, round(width * self.k)))

    def ellipse(self, box, fill=None, outline=None, width=1):
        self.d.ellipse(self.s(*box), fill=fill, outline=outline, width=max(1, round(width * self.k)))

    def line(self, pts, fill, width=1):
        self.d.line(self.s(pts), fill=fill, width=max(1, round(width * self.k)), joint="curve")

    def polygon(self, pts, fill, outline=None):
        self.d.polygon(self.s(pts), fill=fill, outline=outline)

    def text(self, xy, text, size, weight="regular", fill=theme.TEXT, anchor="mm", spacing=6):
        f = theme.pil_font(size * self.k, weight)
        self.d.multiline_text(self.s(*xy), text, font=f, fill=fill, anchor=anchor,
                              align="center", spacing=spacing * self.k)

    def paste(self, im, xy):
        x, y = [int(round(v)) for v in self.s(*xy)]
        self.img.alpha_composite(im.convert("RGBA"), (x, y))


# ---- Mockup-Desktop ------------------------------------------------------

def _desktop(k, bars=None):
    """Bildschirm-Inhalt (ohne Monitor), bars = Animation 0..1 der Balken."""
    sw, sh = SCREEN[2] - SCREEN[0], SCREEN[3] - SCREEN[1]
    img = theme.gradient((int(sw * k), int(sh * k)), "#1c2b4f", "#3a2356").convert("RGBA")
    p = Painter(img, k)
    # Fenster A (hell, Dokument)
    p.rect((18, 16, 232, 150), 8, fill="#eef1f7")
    p.rect((18, 16, 232, 34), 8, fill="#dde2ec")
    p.rect((18, 26, 232, 34), 0, fill="#dde2ec")
    for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        p.ellipse((27 + i * 11, 22, 34 + i * 11, 29), fill=c)
    p.rect((30, 44, 150, 54), 3, fill="#3b4254")
    for i, wdt in enumerate((170, 150, 160, 120)):
        p.rect((30, 64 + i * 12, 30 + wdt, 69 + i * 12), 2, fill="#b9c0cf")
    p.rect((30, 116, 110, 140), 5, fill=theme.ACCENT)
    p.rect((118, 116, 198, 140), 5, fill="#d4d9e4")
    # Fenster B (dunkel, Diagramm)
    p.rect((196, 70, 402, 204), 8, fill=theme.SURFACE, outline=theme.BORDER)
    p.text((212, 86), "Statistik", 9, "semibold", anchor="lm")
    colors = (theme.ACCENT, theme.ACCENT_2, theme.OK, theme.PAUSE, theme.ACCENT)
    base = (0.55, 0.8, 0.45, 0.95, 0.7)
    for i, (c, b) in enumerate(zip(colors, base)):
        hgt = b
        if bars is not None:
            hgt = 0.25 + 0.75 * (0.5 + 0.5 * math.sin(bars * 2 * math.pi + i * 1.1)) * b
        x = 214 + i * 36
        p.rect((x, 190 - 80 * hgt, x + 22, 190), 4, fill=c)
    # Taskleiste
    p.rect((0, sh - 18, sw, sh), 0, fill="#10131a")
    for i in range(5):
        x = sw / 2 - 50 + i * 22
        p.rect((x, sh - 14, x + 12, sh - 4), 3, fill=(theme.ACCENT if i == 2 else "#3a4050"))
    return img


@lru_cache(maxsize=4)
def desktop(k):
    return _desktop(k)


@lru_cache(maxsize=4)
def desktop_dim(k):
    img = desktop(k).convert("RGB")
    dark = ImageEnhance.Brightness(img).enhance(0.42)
    return Image.blend(dark, Image.new("RGB", img.size, (24, 26, 32)), 0.28).convert("RGBA")


def _screen_mask(k):
    sw, sh = SCREEN[2] - SCREEN[0], SCREEN[3] - SCREEN[1]
    mask = Image.new("L", (int(sw * k), int(sh * k)), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, sw * k - 1, sh * k - 1), radius=8 * k, fill=255)
    return mask


def _monitor(p, screen_img):
    x1, y1, x2, y2 = SCREEN
    p.rect((x1 - 9, y1 - 9, x2 + 9, y2 + 9), 16, fill="#23272f", outline="#323845", width=1)
    p.polygon([(270, y2 + 9), (330, y2 + 9), (338, y2 + 24), (262, y2 + 24)], fill="#23272f")
    p.rect((240, y2 + 22, 360, y2 + 28), 3, fill="#2c313b")
    k = p.k
    mask = _screen_mask(k)
    p.img.paste(screen_img, (int(x1 * k), int(y1 * k)), mask)


def _cursor(p, x, y, kind="arrow", alpha=255):
    if kind == "cross":
        for w, c in ((5, (0, 0, 0, alpha // 2)), (2, (255, 255, 255, alpha))):
            p.line([(x - 9, y), (x + 9, y)], c, w)
            p.line([(x, y - 9), (x, y + 9)], c, w)
        return
    shape = [(0, 0), (0, 17), (4, 13), (7, 20), (10, 19), (7, 12), (12, 12)]
    p.polygon([(x + a, y + b) for a, b in shape], fill=(255, 255, 255, alpha), outline=(0, 0, 0, alpha))


def _selection(p, box, color=theme.ACCENT, brackets=True):
    x1, y1, x2, y2 = box
    p.rect(box, 0, outline=color, width=2)
    if brackets:
        L = max(4, min(14, (x2 - x1) / 3, (y2 - y1) / 3))
        theme.draw_brackets(p.d, p.s(x1, y1, x2, y2), L * p.k, max(2, round(3.5 * p.k)),
                            (255, 255, 255, 255))


def _abs(box):
    ox, oy = SCREEN[0], SCREEN[1]
    return (box[0] + ox, box[1] + oy, box[2] + ox, box[3] + oy)


@lru_cache(maxsize=4)
def _glow(k):
    g = Image.new("RGBA", (int(W * k), int(300 * k)), (0, 0, 0, 0))
    d = ImageDraw.Draw(g)
    d.ellipse((190 * k, 20 * k, 410 * k, 210 * k), fill=rgba(theme.ACCENT, 120))
    d.ellipse((260 * k, 60 * k, 440 * k, 230 * k), fill=rgba(theme.ACCENT_2, 80))
    return g.filter(ImageFilter.GaussianBlur(48 * k))


# ---- Szenen --------------------------------------------------------------

def _scene_welcome(p, t):
    k = p.k
    glow = _glow(k)
    a = 0.75 + 0.25 * math.sin(t * 2.2)
    glow = glow.copy()
    glow.putalpha(glow.getchannel("A").point(lambda v: int(v * a)))
    p.img.alpha_composite(glow, (0, 0))
    scale = ease_out_back(t / 0.7)
    size = max(1, int(118 * k * scale))
    logo = theme.logo_image(size)
    p.img.alpha_composite(logo, (int(W * k / 2 - size / 2), int(120 * k - size / 2)))
    chips = [("Bereich wählen", "select"), ("Countdown", "record"), ("1080p", "film"), ("Ton", "speaker")]
    imgs = [theme.pill(txt, int(32 * k), icon=ic) for txt, ic in chips]
    gap = 10 * k
    total = sum(i.width for i in imgs) + gap * (len(imgs) - 1)
    x = W * k / 2 - total / 2
    for i, im in enumerate(imgs):
        e = ease_out_cubic((t - 0.55 - i * 0.15) / 0.45)
        if e > 0:
            im = im.copy()
            im.putalpha(im.getchannel("A").point(lambda v: int(v * e)))
            p.img.alpha_composite(im, (int(x), int((218 + 12 * (1 - e)) * k)))
        x += im.width + gap


def _scene_select(p, t):
    k = p.k
    dim_t = ease_in_out(t / 0.5)
    screen = Image.blend(desktop(k), desktop_dim(k), dim_t)
    sp = Painter(screen, k)
    rx1, ry1, rx2, ry2 = REGION
    drag = ease_in_out((t - 0.8) / 1.2)
    start = (rx1, ry1)
    if t < 0.8:  # Maus fährt zum Startpunkt
        e = ease_in_out((t - 0.2) / 0.6)
        cur = (rx1 + 120 * (1 - e), ry1 + 70 * (1 - e))
    else:
        cur = (rx1 + (rx2 - rx1) * drag, ry1 + (ry2 - ry1) * drag)
    if t < 0.9:
        hint = theme.pill("Bereich aufziehen  ·  Esc = Abbrechen", int(22 * k), icon="select")
        hint.putalpha(hint.getchannel("A").point(lambda v: int(v * dim_t)))
        screen.alpha_composite(hint, (int(screen.width / 2 - hint.width / 2), int(10 * k)))
    if t >= 0.8 and drag > 0.01:
        box = (start[0], start[1], cur[0], cur[1])
        crop = desktop(k).crop([int(v * k) for v in box])
        screen.alpha_composite(crop, (int(box[0] * k), int(box[1] * k)))
        _selection(sp, box)
        wpx, hpx = int((cur[0] - start[0]) * 5.33) // 2 * 2, int((cur[1] - start[1]) * 5.45) // 2 * 2
        lbl = theme.pill(f"{wpx} × {hpx}", int(18 * k))
        screen.alpha_composite(lbl, (int(box[0] * k), max(0, int((box[1] - 23) * k))))
    _cursor(sp, cur[0], cur[1], "cross", int(255 * clamp01((t - 0.2) / 0.3)))
    _monitor(p, screen)


def _scene_countdown(p, t):
    k = p.k
    rec = t >= 3.0
    fade = ease_out_cubic((t - 3.0) / 0.3) if rec else 0
    screen = Image.blend(desktop_dim(k), desktop(k), fade)
    box = REGION
    screen.alpha_composite(desktop(k).crop([int(v * k) for v in box]), (int(box[0] * k), int(box[1] * k)))
    sp = Painter(screen, k)
    if not rec:
        _selection(sp, box)
        size = int(104 * k)
        badge = theme.countdown_badge(size, 3 - int(t), t - int(t), label="")
        cx, cy = (box[0] + box[2]) / 2 * k, (box[1] + box[3]) / 2 * k
        screen.alpha_composite(badge, (int(cx - size / 2), int(cy - size / 2)))
    else:
        _selection(sp, box, theme.REC, brackets=False)
        e = ease_out_back((t - 3.0) / 0.4)
        lbl = theme.pill("REC", int(20 * k), fg="#ffffff", bg=theme.REC, border=None, icon="record")
        lbl = lbl.resize((max(1, int(lbl.width * e)), max(1, int(lbl.height * e))))
        cx, cy = (box[0] + box[2]) / 2 * k, (box[1] + box[3]) / 2 * k
        screen.alpha_composite(lbl, (int(cx - lbl.width / 2), int(cy - lbl.height / 2)))
    _monitor(p, screen)


def _control_bar(k, seconds, paused=False, stop_pressed=False):
    w, h = 150, 28
    img = Image.new("RGBA", (int(w * k), int(h * k)), (0, 0, 0, 0))
    p = Painter(img, k)
    p.rect((0, 0, w - 1, h - 1), 9, fill=theme.SURFACE, outline=theme.BORDER)
    p.ellipse((10, 9, 20, 19), fill=theme.REC)
    p.text((27, 14), f"00:{seconds:02d}", 11, "mono", anchor="lm")
    p.rect((74, 4, 96, 24), 6, fill=theme.SURFACE_2)
    p.paste(theme.icon_image("pause", int(12 * k)), (79, 8))
    p.rect((100, 4, 145, 24), 6, fill=theme.REC_HOVER if stop_pressed else theme.REC)
    p.text((123, 14), "Stopp", 9, "bold", fill="#ffffff")
    return img


def _saved_card(k, scale):
    w, h = 250, 64
    img = Image.new("RGBA", (int(w * k), int(h * k)), (0, 0, 0, 0))
    p = Painter(img, k)
    p.rect((0, 0, w - 1, h - 1), 14, fill=theme.SURFACE, outline=theme.BORDER)
    p.ellipse((14, 16, 46, 48), fill=theme.OK)
    p.paste(theme.icon_image("check", int(24 * k), "#ffffff"), (18, 20))
    p.text((58, 25), "Aufnahme gespeichert", 12, "bold", anchor="lm")
    p.text((58, 43), "1920×1080  ·  mit Ton  ·  00:03", 9, fill=theme.MUTED, anchor="lm")
    if scale < 1:
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
    return img


def _scene_record(p, t):
    k = p.k
    stopped = t >= 3.05
    screen = _desktop(k, bars=t * 0.6)
    sp = Painter(screen, k)
    box = REGION
    if not stopped:
        _selection(sp, box, theme.REC, brackets=False)
        bar = _control_bar(k, int(t), stop_pressed=2.9 <= t < 3.05)
        bx = (box[0] + box[2]) / 2 - 75
        screen.alpha_composite(bar, (int(bx * k), int((box[3] + 9) * k)))
        # Maus fährt zum Stopp-Knopf
        e = ease_in_out((t - 2.0) / 0.8)
        target = (bx + 118, box[3] + 20)
        cur = (330 + (target[0] - 330) * e, 120 + (target[1] - 120) * e)
        _cursor(sp, *cur)
    else:
        e = ease_out_back((t - 3.1) / 0.45)
        if e > 0.02:
            card = _saved_card(k, e)
            sw, sh = screen.size
            screen.alpha_composite(card, (int(sw / 2 - card.width / 2), int(sh / 2 - card.height / 2)))
    _monitor(p, screen)


_SCENE_FUNCS = [_scene_welcome, _scene_select, _scene_countdown, _scene_record]


def render_scene(index, t, k=1.0):
    """Bild einer Szene zum Zeitpunkt t (Sekunden seit Szenenbeginn)."""
    img = Image.new("RGBA", (int(W * k), int(H * k)), rgba(theme.BG))
    p = Painter(img, k)
    _SCENE_FUNCS[index](p, t)
    title, body, _ = SCENES[index]
    e = ease_out_cubic(t / 0.5)
    alpha = int(255 * e)
    dy = 10 * (1 - e)
    p.text((W / 2, 300 + dy), title, 22, "bold", fill=(255, 255, 255, alpha))
    p.text((W / 2, 344 + dy), body, 13.5, "regular", fill=rgba(theme.MUTED, alpha), spacing=5)
    return img


def draw_dots(img, position, k=1.0, count=len(SCENES)):
    """Seiten-Punkte; position darf zwischen zwei Seiten liegen (Animation)."""
    d = ImageDraw.Draw(img)
    gap, small, big, h = 14 * k, 7 * k, 22 * k, 7 * k
    widths = [small + (big - small) * max(0.0, 1 - abs(position - i)) for i in range(count)]
    x = img.width / 2 - (sum(widths) + (gap - small) * (count - 1)) / 2
    y = 384 * k
    for i, wdt in enumerate(widths):
        active = max(0.0, 1 - abs(position - i))
        color = theme.mix(theme.SURFACE_3, theme.ACCENT, active)
        d.rounded_rectangle((x, y - h / 2, x + wdt, y + h / 2), radius=h / 2, fill=color)
        x += wdt + gap - small
    return img


def transition_frame(a_img, b_img, e, direction=1):
    """Szene a schiebt sich raus, b hinein (e = 0..1)."""
    w = a_img.width
    out = Image.new("RGBA", a_img.size, rgba(theme.BG))
    off = int(w * e) * direction
    out.paste(a_img, (-off, 0))
    out.paste(b_img, (w * direction - off, 0))
    return out


def export_gif(path, k=1.0, fps=20):
    """Einführung als GIF speichern (für README/Webseite)."""
    frames = []
    step = 1.0 / fps
    last = None
    for i, (_, _, dur) in enumerate(SCENES):
        if last is not None:
            n = int(TRANSITION * fps)
            for j in range(1, n + 1):
                e = ease_in_out(j / n)
                img = transition_frame(last, render_scene(i, 0, k), e)
                frames.append(draw_dots(img, i - 1 + e, k))
        t = 0.0
        while t < dur:
            img = render_scene(i, t, k)
            frames.append(draw_dots(img.copy(), i, k))
            last = img
            t += step
    # sanfter Übergang zurück zum Anfang
    n = int(TRANSITION * fps)
    for j in range(1, n + 1):
        e = ease_in_out(j / n)
        frames.append(draw_dots(transition_frame(last, render_scene(0, 0, k), e), 3 - 3 * e, k))
    pal = [f.convert("RGB").quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
           for f in frames]
    pal[0].save(path, save_all=True, append_images=pal[1:], duration=int(1000 / fps),
                loop=0, optimize=True, disposal=1)
    return len(frames)


# ---- Fenster -------------------------------------------------------------

def show_intro(master, on_close=None):
    """Einführungsfenster öffnen."""
    import tkinter as tk

    import customtkinter as ctk
    from PIL import ImageTk

    from snaprec.utils import set_alpha

    win = ctk.CTkToplevel(master, fg_color=theme.BG)
    win.title("Willkommen bei SnapRec")
    win.resizable(False, False)
    win.attributes("-topmost", True)
    try:
        k = ctk.ScalingTracker.get_window_scaling(win)
    except Exception:
        k = 1.0
    canvas = tk.Canvas(win, width=int(W * k), height=int(H * k), bg=theme.BG,
                       highlightthickness=0, bd=0)
    canvas.pack(padx=0, pady=(8, 0))
    item = canvas.create_image(0, 0, anchor="nw")

    bar = ctk.CTkFrame(win, fg_color="transparent")
    bar.pack(fill="x", padx=24, pady=(4, 20))
    skip = ctk.CTkButton(bar, text="Überspringen", width=110, height=38, corner_radius=12,
                         fg_color="transparent", hover_color=theme.SURFACE_2, text_color=theme.MUTED,
                         font=ctk.CTkFont(theme.FONT, 13))
    skip.pack(side="left")
    nxt = ctk.CTkButton(bar, text="Weiter", width=140, height=38, corner_radius=12,
                        fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                        font=ctk.CTkFont(theme.FONT, 14, "bold"))
    nxt.pack(side="right")
    back = ctk.CTkButton(bar, text="Zurück", width=100, height=38, corner_radius=12,
                         fg_color=theme.SURFACE_2, hover_color=theme.SURFACE_3,
                         font=ctk.CTkFont(theme.FONT, 13))
    back.pack(side="right", padx=(0, 8))

    state = {"index": 0, "start": time.perf_counter(), "trans": None, "job": None, "photo": None}

    def update_buttons():
        i = state["index"]
        nxt.configure(text="Los geht’s" if i == len(SCENES) - 1 else "Weiter")
        back.configure(state="normal" if i > 0 else "disabled")

    def go(delta):
        new = state["index"] + delta
        if new >= len(SCENES):
            close()
            return
        if new < 0 or state["trans"]:
            return
        now = time.perf_counter()
        old_t = min(now - state["start"], SCENES[state["index"]][2])
        state["trans"] = (render_scene(state["index"], old_t, k), state["index"], new, now)
        state["index"] = new
        update_buttons()

    def tick():
        now = time.perf_counter()
        trans = state["trans"]
        if trans:
            old_img, a, b, t0 = trans
            e = ease_in_out((now - t0) / TRANSITION)
            direction = 1 if b > a else -1
            img = transition_frame(old_img, render_scene(b, 0, k), e, direction)
            img = draw_dots(img, a + (b - a) * e, k)
            if e >= 1:
                state["trans"] = None
                state["start"] = now
        else:
            i = state["index"]
            dur = SCENES[i][2]
            t = now - state["start"]
            if i == 0:
                t = min(t, 20.0)
            elif t > dur + 0.8:  # Szene wiederholen
                state["start"] = now
                t = 0
            img = draw_dots(render_scene(i, min(t, dur), k), i, k)
        state["photo"] = ImageTk.PhotoImage(img.convert("RGB"))
        canvas.itemconfigure(item, image=state["photo"])
        state["job"] = win.after(33, tick)

    def close():
        if state["job"]:
            win.after_cancel(state["job"])
            state["job"] = None
        try:
            win.grab_release()
        except tk.TclError:
            pass
        win.destroy()
        if on_close:
            on_close()

    nxt.configure(command=lambda: go(1))
    back.configure(command=lambda: go(-1))
    skip.configure(command=close)
    win.protocol("WM_DELETE_WINDOW", close)
    win.bind("<Right>", lambda e: go(1))
    win.bind("<Return>", lambda e: go(1))
    win.bind("<Left>", lambda e: go(-1))
    win.bind("<Escape>", lambda e: close())
    update_buttons()

    # mittig über dem Hauptfenster / Bildschirm
    win.update_idletasks()
    ww, wh = win.winfo_reqwidth(), win.winfo_reqheight()
    sx = win.winfo_screenwidth() // 2 - ww // 2
    sy = win.winfo_screenheight() // 2 - wh // 2
    win.wm_geometry(f"+{max(0, sx)}+{max(0, sy)}")
    set_alpha(win, 0.0)
    theme.animate(win, 220, lambda t: set_alpha(win, t))
    win.after(50, lambda: (win.lift(), win.focus_force()))
    try:
        win.grab_set()
    except tk.TclError:
        pass
    tick()
    return win
