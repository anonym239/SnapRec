"""Grauer Bildschirm zum Aufziehen des Bereichs + animierter Countdown."""

import time
import tkinter as tk

from PIL import Image, ImageEnhance, ImageTk

from snaprec import theme
from snaprec.utils import MSS, monitor_at, normalize_region, set_alpha, virtual_screen


class SelectionOverlay(tk.Toplevel):
    """Zeigt einen abgedunkelten Screenshot aller Monitore. Der aufgezogene
    Bereich wird hell dargestellt, danach läuft der Countdown direkt darüber.

    on_done(region) wird nach dem Countdown aufgerufen, on_done(None) bei Abbruch.
    """

    MIN_SIZE = 16

    def __init__(self, master, countdown, on_done, preselect_monitor=False, resolution="original"):
        super().__init__(master)
        self.on_done = on_done
        self.countdown = countdown
        self.resolution = resolution
        # Bei 1080p rastet die Auswahl auf 16:9 bzw. 9:16 ein (Shift = frei)
        from snaprec.processing import TARGETS
        self.lock_ratio = resolution in TARGETS
        self.screen, self.monitors = virtual_screen()
        s = self.screen

        with MSS() as sct:
            shot = sct.grab(s)
        self.full = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        dark = ImageEnhance.Brightness(self.full).enhance(0.42)
        self.dark = Image.blend(dark, Image.new("RGB", self.full.size, (24, 26, 32)), 0.28)

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.geometry(f"{s['width']}x{s['height']}+{s['left']}+{s['top']}")
        self.configure(cursor="crosshair", bg="black")
        set_alpha(self, 0.0)

        c = self.canvas = tk.Canvas(self, width=s["width"], height=s["height"],
                                    highlightthickness=0, bd=0, bg="black")
        c.pack(fill="both", expand=True)
        self._images = {}
        self._dark_tk = ImageTk.PhotoImage(self.dark)
        c.create_image(0, 0, image=self._dark_tk, anchor="nw")
        self._bright_item = c.create_image(0, 0, anchor="nw")
        self._guide_h = c.create_line(0, 0, s["width"], 0, fill="#6b7080", dash=(4, 4))
        self._guide_v = c.create_line(0, 0, 0, s["height"], fill="#6b7080", dash=(4, 4))
        self._rect = c.create_rectangle(0, 0, 0, 0, outline=theme.ACCENT, width=2, state="hidden")
        self._brackets = [c.create_line(0, 0, 0, 0, fill="white", width=4, state="hidden",
                                        capstyle="round", joinstyle="round") for _ in range(4)]
        self._size_item = c.create_image(0, 0, anchor="nw", state="hidden")
        self._hint_item = c.create_image(0, 0, anchor="n")
        self._badge_item = c.create_image(0, 0, anchor="center", state="hidden")

        self._start = None
        self._region = None
        self._pending = None
        self._bright_job = None
        self._count_job = None
        self._closed = False

        c.bind("<Motion>", self._motion)
        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._drag)
        c.bind("<ButtonRelease-1>", self._release)
        c.bind("<Double-Button-1>", self._whole_monitor)
        c.bind("<ButtonPress-3>", lambda e: self.cancel())
        self.bind("<Escape>", lambda e: self.cancel())
        self.bind("<Return>", self._whole_monitor)

        ratio_hint = "   ·   16:9 – Shift = frei" if self.lock_ratio else ""
        self._show_hint("Bereich mit der Maus aufziehen   ·   Doppelklick = ganzer Monitor"
                        f"{ratio_hint}   ·   Esc = Abbrechen", "select")
        self.after(10, self._fade_in)
        if preselect_monitor:
            self.after(60, self._whole_monitor)

    # ---- Darstellung ------------------------------------------------------
    def _fade_in(self):
        self.lift()
        self.focus_force()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        theme.animate(self, 140, lambda t: set_alpha(self, t))

    def _place_image(self, item, img, x, y):
        photo = ImageTk.PhotoImage(img)
        self._images[item] = photo
        self.canvas.itemconfigure(item, image=photo, state="normal")
        self.canvas.coords(item, x, y)

    def _show_hint(self, text, icon):
        m = self.monitors[0] if self.monitors else self.screen
        x = m["left"] - self.screen["left"] + m["width"] // 2
        y = m["top"] - self.screen["top"] + 28
        self._place_image(self._hint_item, theme.pill(text, 40, icon=icon), x, y)
        self.canvas.tag_raise(self._hint_item)

    def _set_selection(self, left, top, right, bottom):
        c = self.canvas
        c.coords(self._rect, left, top, right, bottom)
        c.itemconfigure(self._rect, state="normal")
        L = max(4, min(18, (right - left) // 3, (bottom - top) // 3))
        pts = [
            (left, top + L, left, top, left + L, top),
            (right - L, top, right, top, right, top + L),
            (left, bottom - L, left, bottom, left + L, bottom),
            (right - L, bottom, right, bottom, right, bottom - L),
        ]
        for item, p in zip(self._brackets, pts):
            c.coords(item, *p)
            c.itemconfigure(item, state="normal")
            c.tag_raise(item)

        w, h = (right - left) // 2 * 2, (bottom - top) // 2 * 2
        text = f"{w} × {h}"
        fg = theme.TEXT
        if self.lock_ratio and w > 0 and h > 0:
            from snaprec.processing import RESOLUTION_LABELS, output_size, upscale_factor
            ow, oh = output_size(w, h, self.resolution)
            text += f"   →   {RESOLUTION_LABELS[self.resolution]}  ({ow} × {oh})"
            if upscale_factor(w, h, self.resolution) > 1.05:
                text += "  ·  wird smart hochskaliert"
                fg = "#b9a8ff"
        label = theme.pill(text, 28, fg=fg)
        ly = top - label.height - 8 if top > label.height + 12 else bottom + 8
        self._place_image(self._size_item, label, left, ly)

        self._pending = (left, top, right, bottom)
        if not self._bright_job:
            self._bright_job = self.after_idle(self._render_bright)

    def _render_bright(self):
        """Heller Ausschnitt – nur einmal pro Leerlauf neu zeichnen, damit das
        Ziehen flüssig bleibt und trotzdem die letzte Position stimmt."""
        self._bright_job = None
        left, top, right, bottom = self._pending
        if right - left < 2 or bottom - top < 2:
            self.canvas.itemconfigure(self._bright_item, state="hidden")
            return
        self._place_image(self._bright_item, self.full.crop((left, top, right, bottom)), left, top)
        self.canvas.tag_raise(self._rect)
        for item in self._brackets:
            self.canvas.tag_raise(item)

    def _hide_selection(self):
        for item in [self._rect, self._size_item, self._bright_item] + self._brackets:
            self.canvas.itemconfigure(item, state="hidden")

    # ---- Maus -------------------------------------------------------------
    def _clamp(self, x, y):
        return (min(max(x, 0), self.screen["width"]), min(max(y, 0), self.screen["height"]))

    def _motion(self, event):
        if self._region:
            return
        self.canvas.coords(self._guide_h, 0, event.y, self.screen["width"], event.y)
        self.canvas.coords(self._guide_v, event.x, 0, event.x, self.screen["height"])

    def _press(self, event):
        if self._region:  # Klick während des Countdowns = sofort starten
            self._finish_countdown()
            return
        self._start = self._clamp(event.x, event.y)
        for item in (self._guide_h, self._guide_v, self._hint_item):
            self.canvas.itemconfigure(item, state="hidden")

    def _constrain(self, x2, y2, state=0):
        """Auf 16:9 (quer) bzw. 9:16 (hochkant) einrasten, außer Shift ist gedrückt."""
        if not self.lock_ratio or state & 0x0001:
            return x2, y2
        x1, y1 = self._start
        dx, dy = x2 - x1, y2 - y1
        sx, sy = (1 if dx >= 0 else -1), (1 if dy >= 0 else -1)
        w, h = abs(dx), abs(dy)
        ratio = 16 / 9 if w >= h else 9 / 16
        if ratio > 1:
            h = w / ratio
        else:
            w = h * ratio
        max_w = self.screen["width"] - x1 if sx > 0 else x1
        max_h = self.screen["height"] - y1 if sy > 0 else y1
        if w > max_w:
            w, h = max_w, max_w / ratio
        if h > max_h:
            h, w = max_h, max_h * ratio
        return round(x1 + sx * w), round(y1 + sy * h)

    def _drag(self, event):
        if not self._start or self._region:
            return
        x1, y1 = self._start
        x2, y2 = self._constrain(*self._clamp(event.x, event.y), event.state)
        self._set_selection(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))

    def _release(self, event):
        if not self._start or self._region:
            return
        x1, y1 = self._start
        x2, y2 = self._constrain(*self._clamp(event.x, event.y), event.state)
        self._start = None
        ox, oy = self.screen["left"], self.screen["top"]
        region = normalize_region(x1 + ox, y1 + oy, x2 + ox, y2 + oy)
        if region["width"] < self.MIN_SIZE or region["height"] < self.MIN_SIZE:
            self._hide_selection()  # nur ein Klick – nochmal versuchen
            for item in (self._guide_h, self._guide_v, self._hint_item):
                self.canvas.itemconfigure(item, state="normal")
            return
        self._accept(region)

    def _whole_monitor(self, event=None):
        if self._region or self._closed:
            return
        px, py = self.winfo_pointerxy()
        m = monitor_at(px, py, self.monitors) if self.monitors else self.screen
        self._accept(normalize_region(m["left"], m["top"],
                                      m["left"] + m["width"], m["top"] + m["height"]))

    # ---- Countdown --------------------------------------------------------
    def _accept(self, region):
        self._region = region
        ox, oy = self.screen["left"], self.screen["top"]
        left, top = region["left"] - ox, region["top"] - oy
        right, bottom = left + region["width"], top + region["height"]
        self._set_selection(left, top, right, bottom)
        self.update_idletasks()
        for item in (self._guide_h, self._guide_v, self._size_item):
            self.canvas.itemconfigure(item, state="hidden")
        self.configure(cursor="arrow")
        if self.countdown <= 0:
            self._finish_countdown()
            return

        # Hintergrund für den Countdown: dunkel + heller Bereich
        self._composed = self.dark.copy()
        self._composed.paste(self.full.crop((left, top, right, bottom)), (left, top))
        size = int(max(130, min(230, min(region["width"], region["height"]) * 0.62)))
        cx, cy = (left + right) // 2, (top + bottom) // 2
        self._badge_box = (cx - size // 2, cy - size // 2, cx - size // 2 + size, cy - size // 2 + size)
        self._badge_size = size
        self._show_hint("Aufnahme startet gleich   ·   Klick = sofort   ·   Esc = Abbrechen", "record")
        self.canvas.itemconfigure(self._hint_item, state="normal")
        self._count_start = time.perf_counter()
        self._tick()

    def _tick(self):
        self._count_job = None
        elapsed = time.perf_counter() - self._count_start
        if elapsed >= self.countdown:
            self._finish_countdown()
            return
        number = self.countdown - int(elapsed)
        frac = elapsed - int(elapsed)
        badge = theme.countdown_badge(self._badge_size, number, frac)
        bg = self._composed.crop(self._badge_box).convert("RGBA")
        bg.alpha_composite(badge)
        x1, y1, x2, y2 = self._badge_box
        self._place_image(self._badge_item, bg.convert("RGB"), (x1 + x2) // 2, (y1 + y2) // 2)
        self.canvas.tag_raise(self._badge_item)
        self._count_job = self.after(16, self._tick)

    def _finish_countdown(self):
        if self._closed:
            return
        region = self._region
        self._close()
        self.on_done(region)

    def cancel(self):
        if self._closed:
            return
        self._close()
        self.on_done(None)

    def _close(self):
        self._closed = True
        for job in (self._count_job, self._bright_job):
            if job:
                self.after_cancel(job)
        self._count_job = self._bright_job = None
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
