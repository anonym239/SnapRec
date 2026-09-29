"""Ladebildschirm während der smarten Nachbearbeitung."""

import math
import time
import tkinter as tk

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

from snaprec import APP_NAME, theme
from snaprec.processing import RESOLUTION_LABELS, output_size, upscale_factor
from snaprec.utils import set_alpha

RING = 150


def font(size, weight="normal"):
    return ctk.CTkFont(theme.FONT, size, weight)


def ring_image(size, progress, spin=None, text=""):
    """Fortschrittsring (progress 0..1) oder drehender Bogen (spin = Winkel)."""
    k = 2
    s = size * k
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    w = int(s * 0.07)
    box = (w, w, s - w, s - w)
    d.ellipse(box, outline=theme.rgba(theme.SURFACE_3), width=w)
    mask = Image.new("L", (s, s), 0)
    md = ImageDraw.Draw(mask)
    if spin is not None:
        start, end = spin, spin + 100
    else:
        start, end = -90, -90 + 360 * max(0.0, min(1.0, progress))
    if end - start > 0.5:
        md.arc(box, start, end, fill=255, width=w)
        c, r = s / 2, (s - 2 * w) / 2
        for ang in (start, end):
            x, y = c + math.cos(math.radians(ang)) * r, c + math.sin(math.radians(ang)) * r
            md.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=255)
        img.paste(theme.gradient((s, s)).convert("RGBA"), (0, 0), mask)
    if text:
        d.text((s / 2, s / 2), text, font=theme.pil_font(int(s * 0.2), "bold"),
               fill=theme.rgba(theme.TEXT), anchor="mm")
    return img.resize((size, size), Image.Resampling.LANCZOS)


class LoadingWindow(ctk.CTkToplevel):
    """Zeigt Schritte, Fortschritt und Analyse der Verarbeitung.
    on_done(processor) wird aufgerufen, sobald alles fertig ist."""

    def __init__(self, app, processor, on_done):
        super().__init__(app.root, fg_color=theme.BG)
        self.app = app
        self.proc = processor
        self.on_done = on_done
        self.title(f"{APP_NAME} – Video wird fertiggestellt")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", lambda: None)   # erst schließen, wenn fertig
        app.apply_icon(self)

        w, h = processor.src_size
        res = processor.resolution
        self.upscaling = upscale_factor(w, h, res) > 1.02
        ow, oh = output_size(w, h, res)
        label = RESOLUTION_LABELS.get(res, res)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(padx=24, pady=(22, 12), fill="both")
        self.canvas = tk.Canvas(body, width=RING, height=RING, bg=theme.BG, highlightthickness=0)
        self.canvas.pack(side="left", padx=(0, 22), anchor="n")
        self.ring_item = self.canvas.create_image(RING // 2, RING // 2)

        right = ctk.CTkFrame(body, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)
        ctk.CTkLabel(right, text="Video wird fertiggestellt", font=font(19, "bold"),
                     text_color=theme.TEXT, anchor="w").pack(fill="x")
        sub = (f"{w} × {h}  →  {label}  ({ow} × {oh})" if self.upscaling or (w, h) != (ow, oh)
               else f"{ow} × {oh}")
        ctk.CTkLabel(right, text=sub, font=font(12), text_color=theme.MUTED, anchor="w").pack(fill="x", pady=(0, 10))

        steps = [("rec", "Aufnahme gespeichert")]
        if self.upscaling:
            steps.append(("analyse", "Inhalt analysieren"))
            steps.append(("render", f"Smart hochskalieren auf {label}"))
        elif (w, h) != (ow, oh):
            steps.append(("render", f"Auf {label} umrechnen"))
        else:
            steps.append(("render", "Video fertig kodieren"))
        steps.append(("save", "Ton einmischen & speichern" if processor.tracks else "Speichern"))
        self.steps = {}
        for key, text in steps:
            row = ctk.CTkFrame(right, fg_color="transparent")
            row.pack(fill="x", pady=2)
            icon = ctk.CTkLabel(row, text="", width=22)
            icon.pack(side="left")
            lbl = ctk.CTkLabel(row, text=text, font=font(13), text_color=theme.MUTED, anchor="w")
            lbl.pack(side="left", padx=(6, 0))
            pct = ctk.CTkLabel(row, text="", font=font(12, "bold"), text_color=theme.ACCENT)
            pct.pack(side="right")
            self.steps[key] = (icon, lbl, pct)
        self._icons = {
            "done": theme.ctk_icon("check_circle", 18),
            "active": ctk.CTkImage(self._dot(theme.ACCENT), self._dot(theme.ACCENT), size=(18, 18)),
            "wait": ctk.CTkImage(self._dot(theme.SURFACE_3), self._dot(theme.SURFACE_3), size=(18, 18)),
        }

        self.info = ctk.CTkFrame(self, fg_color=theme.SURFACE, corner_radius=14, border_width=1,
                                 border_color=theme.BORDER)
        self.info_label = ctk.CTkLabel(self.info, text="", font=font(12), text_color=theme.TEXT,
                                       anchor="w", justify="left", wraplength=470)
        self.info_label.pack(fill="x", padx=16, pady=12)

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=24, pady=(4, 20), side="bottom")
        self.eta = ctk.CTkLabel(foot, text="", font=font(12), text_color=theme.MUTED)
        self.eta.pack(side="left")
        self.skip = ctk.CTkButton(foot, text="Überspringen", height=34, corner_radius=10, font=font(12),
                                  fg_color=theme.SURFACE_2, hover_color=theme.SURFACE_3,
                                  command=self._skip)
        if self.upscaling:
            self.skip.pack(side="right")

        self._start = time.perf_counter()
        self._shown_info = False
        self.update_idletasks()
        root = app.root
        x = root.winfo_rootx() + root.winfo_width() // 2 - self.winfo_reqwidth() // 2
        y = root.winfo_rooty() + 40
        self.wm_geometry(f"+{max(0, x)}+{max(0, y)}")
        set_alpha(self, 0.0)
        theme.animate(self, 200, lambda t: set_alpha(self, t))
        self._tick()

    @staticmethod
    def _dot(color):
        img = Image.new("RGBA", (72, 72), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse((20, 20, 52, 52), fill=theme.rgba(color))
        return img

    def _skip(self):
        self.skip.configure(state="disabled", text="Wird übersprungen …")
        self.proc.cancel()

    def _set_step(self, key, state, pct=""):
        if key not in self.steps:
            return
        icon, lbl, pct_lbl = self.steps[key]
        icon.configure(image=self._icons[state])
        lbl.configure(text_color=theme.TEXT if state != "wait" else theme.MUTED,
                      font=font(13, "bold" if state == "active" else "normal"))
        pct_lbl.configure(text=pct)

    def _show_info(self):
        p = self.proc
        lines = []
        if p.analysis:
            lines.append(f"Erkannt: {p.analysis.label}"
                         + ("  ·  Quelle etwas unscharf" if p.analysis.blurry else ""))
        if p.plan and p.plan.steps and self.upscaling:
            lines.append("Methode: " + "  →  ".join(s.split(" – ")[0] for s in p.plan.steps))
            lines.append(f"Vergrößerung: ×{p.plan.factor:.1f}".replace(".", ","))
        if lines:
            self.info_label.configure(text="\n".join(lines))
            self.info.pack(fill="x", padx=24, pady=(0, 8), before=self.eta.master)
            theme.animate(self.info, 500, lambda t: self.info.configure(
                border_color=theme.mix(theme.ACCENT, theme.BORDER, t)))
        self._shown_info = True

    def _tick(self):
        if not self.winfo_exists():
            return
        p = self.proc
        now = time.perf_counter()
        self._set_step("rec", "done")
        spin = None
        if p.phase == "analyse":
            self._set_step("analyse", "active")
            spin = (now * 360) % 360
            ring_text = "…"
        else:
            self._set_step("analyse", "done")
            if not self._shown_info and p.plan:
                self._show_info()
            pct = int(p.progress * 100)
            ring_text = f"{pct} %"
            if p.phase in ("render", "fallback"):
                label = f"{pct} %"
                self._set_step("render", "active", label)
                if p.phase == "fallback":
                    self.steps["render"][1].configure(text="Ohne Hochskalieren speichern")
                self._set_step("save", "active" if pct >= 99 else "wait")
            elif p.phase == "done":
                self._set_step("render", "done", "")
                self._set_step("save", "done")
        photo = ImageTk.PhotoImage(ring_image(RING, p.progress, spin, ring_text))
        self._photo = photo
        self.canvas.itemconfigure(self.ring_item, image=photo)
        if p.eta is not None and p.phase == "render":
            eta = max(1, int(p.eta))
            self.eta.configure(text=f"noch ca. {eta} s" if eta < 90 else f"noch ca. {eta // 60} min")
        elif p.phase == "analyse":
            self.eta.configure(text="Analysiere Bildinhalt …")
        elif p.phase == "render":
            self.eta.configure(text="Berechne Restzeit …")
        elif p.phase == "fallback":
            self.eta.configure(text="Speichere in Originalgröße …")

        if p.phase == "done" and not p.is_alive():
            self.after(450, self._finish)
            return
        self.after(40, self._tick)

    def _finish(self):
        if not self.winfo_exists():
            return
        self.destroy()
        self.on_done(self.proc)
