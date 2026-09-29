"""Kurze Tour: hebt die Knöpfe im Hauptfenster nacheinander hervor –
mit Spotlight, Pfeil und kleiner Beschriftung."""

import tkinter as tk

from PIL import Image, ImageDraw, ImageEnhance, ImageTk

from snaprec import hotkeys, theme
from snaprec.utils import MSS, monitor_at, set_alpha, virtual_screen

BUBBLE_W = 310
PAD = 7


def _wrap(text, font, width):
    lines = []
    for para in text.split("\n"):
        line = ""
        for word in para.split():
            test = f"{line} {word}".strip()
            if font.getlength(test) <= width:
                line = test
            else:
                if line:
                    lines.append(line)
                line = word
        lines.append(line)
    return lines


def steps_for(app):
    """(Widget(s), Titel, Text) für jeden Schritt."""
    combo = app.cfg["hotkeys"].get("toggle")
    key = f"\nKürzel: {hotkeys.label(combo)}" if combo else ""
    full = app.cfg["hotkeys"].get("fullscreen")
    full_key = f"\nKürzel: {hotkeys.label(full)}" if full else ""
    return [
        ([app.new_btn], "Neue Aufnahme",
         "Hier startest du. Der Bildschirm wird grau und du ziehst mit der Maus den Bereich auf." + key),
        ([app.full_btn], "Vollbild",
         "Nimmt sofort den ganzen Monitor auf – das wird am schärfsten." + full_key),
        ([app.countdown], "Countdown",
         "Wartezeit vor dem Start: aus, 3, 5 oder 10 Sekunden. Esc bricht ab."),
        ([app.quality], "Qualität",
         "Original, 1080p, 1440p oder 4K. Ist dein Bereich kleiner, wird das Video danach "
         "automatisch analysiert und smart hochskaliert."),
        ([b for b, _ in app.audio_btns.values()], "Ton",
         "PC-Sound (was du hörst) und/oder Mikrofon mit aufnehmen. Lila = eingeschaltet."),
        ([app.film_btn], "Meine Aufnahmen",
         "Alle Videos mit Vorschau – abspielen oder löschen (landen im Papierkorb)."),
        ([app.help_btn], "Hilfe",
         "Startet diese Tour jederzeit neu (oder F1)."),
        ([app.gear_btn], "Einstellungen",
         "Eigene Tastenkürzel, Bildrate, Mauszeiger, Speicherort und mehr."),
        ([app.footer], "Speicherort",
         "Hier landen deine Videos. Ein Klick öffnet den Ordner."),
    ]


class Tour(tk.Toplevel):
    def __init__(self, app, on_close=None):
        super().__init__(app.root)
        self.app = app
        self.on_close = on_close
        root = app.root
        root.deiconify()
        root.lift()
        root.update()
        self.screen, self.monitors = virtual_screen()
        s = self.screen
        with MSS() as sct:
            shot = sct.grab(s)
        self.full = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        dark = ImageEnhance.Brightness(self.full).enhance(0.35)
        self.dark = Image.blend(dark, Image.new("RGB", self.full.size, (20, 22, 28)), 0.3)

        self.steps = steps_for(app)
        self.boxes = [self._bbox(ws) for ws, _, _ in self.steps]
        mon = monitor_at(root.winfo_rootx() + 5, root.winfo_rooty() + 5, self.monitors) \
            if self.monitors else s
        self.mon = (mon["left"] - s["left"], mon["top"] - s["top"],
                    mon["left"] - s["left"] + mon["width"], mon["top"] - s["top"] + mon["height"])
        self.win_box = self._bbox([root])

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.geometry(f"{s['width']}x{s['height']}+{s['left']}+{s['top']}")
        set_alpha(self, 0.0)
        c = self.canvas = tk.Canvas(self, width=s["width"], height=s["height"], highlightthickness=0,
                                    bd=0, bg="black", cursor="arrow")
        c.pack(fill="both", expand=True)
        self._dark_tk = ImageTk.PhotoImage(self.dark)
        c.create_image(0, 0, image=self._dark_tk, anchor="nw")
        self.spot_item = c.create_image(0, 0, anchor="nw")
        self.frame_item = c.create_rectangle(0, 0, 0, 0, outline=theme.ACCENT, width=3)
        self.arrow_item = c.create_line(0, 0, 0, 0, fill="white", width=3, arrow="last",
                                        arrowshape=(14, 16, 6), capstyle="round", smooth=True)
        self.bubble_item = c.create_image(0, 0, anchor="nw")
        self._images = {}
        self.index = 0
        self.spot = self.boxes[0]
        self.buttons = {}

        c.bind("<Button-1>", self._click)
        for key in ("<Right>", "<Return>", "<space>"):
            self.bind(key, lambda e: self.go(1))
        self.bind("<Left>", lambda e: self.go(-1))
        self.bind("<Escape>", lambda e: self.close())
        self._show(0, animate=False)
        theme.animate(self, 200, lambda t: set_alpha(self, t))
        self.after(50, lambda: (self.focus_force(), self.lift()))

    # ---- Geometrie -------------------------------------------------------------
    def _bbox(self, widgets):
        xs, ys, xe, ye = [], [], [], []
        for w in widgets:
            w.update_idletasks()
            x, y = w.winfo_rootx() - self.screen["left"], w.winfo_rooty() - self.screen["top"]
            xs.append(x)
            ys.append(y)
            xe.append(x + w.winfo_width())
            ye.append(y + w.winfo_height())
        return (min(xs) - PAD, min(ys) - PAD, max(xe) + PAD, max(ye) + PAD)

    def _place_bubble(self, box, bw, bh):
        """Sprechblase neben das Hauptfenster setzen (rechts, sonst links/unten)."""
        mx1, my1, mx2, my2 = self.mon
        wx1, wy1, wx2, wy2 = self.win_box
        cy = (box[1] + box[3]) / 2
        y = max(my1 + 12, min(cy - bh / 2, my2 - bh - 12))
        if wx2 + 60 + bw <= mx2:
            return wx2 + 60, y, "right"
        if wx1 - 60 - bw >= mx1:
            return wx1 - 60 - bw, y, "left"
        x = max(mx1 + 12, min((box[0] + box[2]) / 2 - bw / 2, mx2 - bw - 12))
        if wy2 + 40 + bh <= my2:
            return x, wy2 + 40, "below"
        return x, max(my1 + 12, wy1 - 40 - bh), "above"

    # ---- Darstellung -------------------------------------------------------------
    def _bubble(self, i):
        k = 2
        _, title, text = self.steps[i]
        n = len(self.steps)
        fb = theme.pil_font(15 * k, "bold")
        fr = theme.pil_font(12 * k, "regular")
        fs = theme.pil_font(11 * k, "semibold")
        inner = (BUBBLE_W - 36) * k
        lines = _wrap(text, fr, inner)
        h = (18 + 20 + 26 + len(lines) * 18 + 14 + 16 + 32 + 16) * k
        w = BUBBLE_W * k
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((0, 0, w - 1, h - 1), radius=16 * k, fill=theme.rgba(theme.SURFACE),
                            outline=theme.rgba(theme.ACCENT), width=2 * k)
        x, y = 18 * k, 16 * k
        d.text((x, y), f"SCHRITT {i + 1} VON {n}", font=fs, fill=theme.rgba(theme.ACCENT))
        y += 22 * k
        d.text((x, y), title, font=fb, fill=theme.rgba(theme.TEXT))
        y += 28 * k
        for line in lines:
            d.text((x, y), line, font=fr, fill=theme.rgba("#c9cedb"))
            y += 18 * k
        y += 12 * k
        # Punkte (eigene Zeile über den Knöpfen)
        for j in range(n):
            px = x + j * 12 * k
            wide = 10 * k if j == i else 6 * k
            d.rounded_rectangle((px, y, px + wide, y + 6 * k), radius=3 * k,
                                fill=theme.rgba(theme.ACCENT if j == i else theme.SURFACE_3))
            if j == i:
                x += 4 * k
        x = 18 * k
        y += 16 * k
        # Knöpfe
        buttons = {}
        bw_next = 92 * k
        nx2 = w - 16 * k
        nx1 = nx2 - bw_next
        d.rounded_rectangle((nx1, y, nx2, y + 32 * k), radius=9 * k, fill=theme.rgba(theme.ACCENT))
        d.text(((nx1 + nx2) / 2, y + 16 * k), "Fertig" if i == n - 1 else "Weiter  →",
               font=theme.pil_font(12 * k, "bold"), fill=(255, 255, 255, 255), anchor="mm")
        buttons["next"] = (nx1 / k, y / k, nx2 / k, (y + 32 * k) / k)
        if i > 0:
            bx2 = nx1 - 8 * k
            bx1 = bx2 - 76 * k
            d.rounded_rectangle((bx1, y, bx2, y + 32 * k), radius=9 * k, fill=theme.rgba(theme.SURFACE_2))
            d.text(((bx1 + bx2) / 2, y + 16 * k), "Zurück", font=theme.pil_font(12 * k, "semibold"),
                   fill=theme.rgba(theme.TEXT), anchor="mm")
            buttons["back"] = (bx1 / k, y / k, bx2 / k, (y + 32 * k) / k)
        d.text((w - 16 * k, 16 * k), "Esc = Beenden", font=theme.pil_font(10 * k), fill=theme.rgba(theme.MUTED),
               anchor="ra")
        buttons["close"] = ((w - 100 * k) / k, 8, (w - 8 * k) / k, 34)
        return img.resize((w // k, h // k), Image.Resampling.LANCZOS), buttons

    def _set_spot(self, box):
        x1, y1, x2, y2 = [int(round(v)) for v in box]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(self.full.width, x2), min(self.full.height, y2)
        if x2 - x1 < 2 or y2 - y1 < 2:
            return
        photo = ImageTk.PhotoImage(self.full.crop((x1, y1, x2, y2)))
        self._images["spot"] = photo
        self.canvas.itemconfigure(self.spot_item, image=photo)
        self.canvas.coords(self.spot_item, x1, y1)
        self.canvas.coords(self.frame_item, x1, y1, x2, y2)

    def _show(self, i, animate=True):
        self.index = i
        target = self.boxes[i]
        start = self.spot
        img, buttons = self._bubble(i)
        bx, by, side = self._place_bubble(target, img.width, img.height)
        photo = ImageTk.PhotoImage(img)
        self._images["bubble"] = photo
        self.canvas.itemconfigure(self.bubble_item, image=photo)
        self.bubble_pos = (bx, by)
        self.buttons = buttons
        self.canvas.itemconfigure(self.arrow_item, state="hidden")

        def arrow():
            tx1, ty1, tx2, ty2 = target
            if side == "right":
                sx, sy = bx - 4, min(max((ty1 + ty2) / 2, by + 20), by + img.height - 20)
                ex, ey = tx2 + 6, (ty1 + ty2) / 2
            elif side == "left":
                sx, sy = bx + img.width + 4, min(max((ty1 + ty2) / 2, by + 20), by + img.height - 20)
                ex, ey = tx1 - 6, (ty1 + ty2) / 2
            elif side == "below":
                sx, sy = bx + img.width / 2, by - 4
                ex, ey = (tx1 + tx2) / 2, ty2 + 6
            else:
                sx, sy = bx + img.width / 2, by + img.height + 4
                ex, ey = (tx1 + tx2) / 2, ty1 - 6
            mx, my = (sx + ex) / 2, (sy + ey) / 2 - 18
            self.canvas.coords(self.arrow_item, sx, sy, mx, my, ex, ey)
            self.canvas.itemconfigure(self.arrow_item, state="normal")
            self.canvas.tag_raise(self.arrow_item)

        def step(t):
            box = tuple(a + (b - a) * t for a, b in zip(start, target))
            self.spot = box
            self._set_spot(box)
            self.canvas.coords(self.bubble_item, bx + 16 * (1 - t), by)
            set_bubble_alpha(t)

        def set_bubble_alpha(t):
            if t >= 1:
                self.canvas.itemconfigure(self.bubble_item, image=self._images["bubble"])
                return
            faded = img.copy()
            faded.putalpha(faded.getchannel("A").point(lambda v: int(v * t)))
            ph = ImageTk.PhotoImage(faded)
            self._images["bubble_fade"] = ph
            self.canvas.itemconfigure(self.bubble_item, image=ph)

        if animate:
            theme.animate(self, 320, step, done=arrow, ease=theme.ease_in_out)
        else:
            step(1.0)
            arrow()

    # ---- Bedienung -------------------------------------------------------------
    def _click(self, event):
        bx, by = self.bubble_pos
        for name, (x1, y1, x2, y2) in self.buttons.items():
            if bx + x1 <= event.x <= bx + x2 and by + y1 <= event.y <= by + y2:
                if name == "next":
                    self.go(1)
                elif name == "back":
                    self.go(-1)
                else:
                    self.close()
                return
        self.go(1)   # Klick irgendwohin = weiter

    def go(self, delta):
        new = self.index + delta
        if new >= len(self.steps):
            self.close()
        elif new >= 0:
            self._show(new)

    def close(self):
        if not self.winfo_exists():
            return
        self.destroy()
        if self.on_close:
            self.on_close()
