"""Fenster während der Aufnahme: Rahmen um den Bereich und Steuerleiste."""

import math
import time
import tkinter as tk

import customtkinter as ctk

from snaprec import theme
from snaprec.utils import exclude_from_capture, format_time, round_corners, set_alpha, virtual_screen


class RegionFrame:
    """Farbiger Rahmen AUSSERHALB des Bereichs – wird nicht mit aufgenommen."""

    def __init__(self, master, region, color, thickness=3):
        self.wins = []
        self.color = color
        l, t, w, h = region["left"], region["top"], region["width"], region["height"]
        d = thickness
        parts = [
            (l - d, t - d, w + 2 * d, d),   # oben
            (l - d, t + h, w + 2 * d, d),   # unten
            (l - d, t, d, h),               # links
            (l + w, t, d, h),               # rechts
        ]
        for x, y, pw, ph in parts:
            win = tk.Toplevel(master)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(bg=color)
            win.geometry(f"{pw}x{ph}+{x}+{y}")
            exclude_from_capture(win)
            self.wins.append(win)

    def set_color(self, color, duration=250):
        start = self.color
        self.color = color
        if not self.wins:
            return

        def step(t):
            for win in self.wins:
                if win.winfo_exists():
                    win.configure(bg=theme.mix(start, color, t))
        theme.animate(self.wins[0], duration, step)

    def destroy(self):
        for win in self.wins:
            win.destroy()
        self.wins = []


class ControlBar(tk.Toplevel):
    """Schwebende Leiste mit pulsierendem Punkt, Zeit, Pause und Stopp."""

    def __init__(self, master, region, on_pause, on_stop, stop_hint=""):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg=theme.SURFACE, highlightthickness=1,
                       highlightbackground=theme.BORDER, highlightcolor=theme.BORDER)
        set_alpha(self, 0.0)
        self.paused = False
        self.elapsed = 0.0

        grip = tk.Canvas(self, width=10, height=22, bg=theme.SURFACE, highlightthickness=0,
                         cursor="fleur")
        for gx in (2, 7):
            for gy in (3, 10, 17):
                grip.create_oval(gx, gy, gx + 2, gy + 2, fill=theme.MUTED, outline="")
        grip.pack(side="left", padx=(10, 6), pady=8)

        self.dot = tk.Canvas(self, width=14, height=14, bg=theme.SURFACE, highlightthickness=0)
        self.dot_item = self.dot.create_oval(1, 1, 13, 13, fill=theme.REC, outline="")
        self.dot.pack(side="left", padx=(2, 8))

        self.time = ctk.CTkLabel(self, text="00:00", text_color=theme.TEXT, width=58,
                                 font=ctk.CTkFont(theme.MONO, 16, "bold"), anchor="w")
        self.time.pack(side="left", padx=(0, 8))

        self._icons = {n: theme.ctk_icon(n, 14) for n in ("pause", "play")}
        self.pause_btn = ctk.CTkButton(
            self, text="", image=self._icons["pause"], width=36, height=34, corner_radius=10,
            fg_color=theme.SURFACE_2, hover_color=theme.SURFACE_3, command=on_pause)
        self.pause_btn.pack(side="left", padx=(0, 6), pady=8)
        ctk.CTkButton(
            self, text="Stopp", image=theme.ctk_icon("stop", 12, "#ffffff"), width=92, height=34,
            corner_radius=10, fg_color=theme.REC, hover_color=theme.REC_HOVER,
            text_color="#ffffff", font=ctk.CTkFont(theme.FONT, 13, "bold"),
            command=on_stop).pack(side="left", padx=(0, 8), pady=8)
        if stop_hint:
            ctk.CTkLabel(self, text=stop_hint, text_color=theme.MUTED,
                         font=ctk.CTkFont(theme.FONT, 11)).pack(side="left", padx=(0, 12))

        self.update_idletasks()
        bw, bh = self.winfo_reqwidth(), self.winfo_reqheight()
        screen, _ = virtual_screen()
        x = region["left"] + region["width"] // 2 - bw // 2
        x = max(screen["left"], min(x, screen["left"] + screen["width"] - bw))
        below = region["top"] + region["height"] + 12
        above = region["top"] - bh - 12
        if below + bh <= screen["top"] + screen["height"]:
            y = below
        elif above >= screen["top"]:
            y = above
        else:  # Bereich ist so groß wie der Bildschirm -> unten innen
            y = region["top"] + region["height"] - bh - 24
        self.geometry(f"+{x}+{y}")
        round_corners(self)
        exclude_from_capture(self)
        theme.animate(self, 200, lambda t: set_alpha(self, 0.97 * t))

        for w in (self, grip, self.dot):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
        self._pulse()

    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.winfo_x(), e.y_root - self.winfo_y()

    def _drag_move(self, e):
        self.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def _pulse(self):
        if not self.winfo_exists():
            return
        if self.paused:
            color = theme.PAUSE
        else:
            t = 0.5 - 0.5 * math.cos(time.perf_counter() * math.pi * 1.6)
            color = theme.mix(theme.REC, theme.SURFACE, t * 0.75)
        self.dot.itemconfigure(self.dot_item, fill=color)
        self.after(33, self._pulse)

    def update_state(self, elapsed, paused):
        self.elapsed, self.paused = elapsed, paused
        self.time.configure(text=format_time(elapsed))
        self.pause_btn.configure(image=self._icons["play" if paused else "pause"])
