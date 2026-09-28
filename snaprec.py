#!/usr/bin/env python3
"""SnapRec – einen Bildschirmbereich als Video aufnehmen.

Funktioniert wie die Bildschirmaufnahme im Snipping Tool von Windows 11:
Der Bildschirm wird grau abgedunkelt, du ziehst mit der Maus den Bereich auf,
nach einem einstellbaren Countdown (z. B. 3 Sekunden) startet die Aufnahme.
Das Ergebnis wird als MP4 (H.264) gespeichert.

Lizenz: MIT
"""

import argparse
import ctypes
import datetime
import json
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    import mss
    import imageio_ffmpeg
    from PIL import Image, ImageDraw, ImageEnhance, ImageTk
except ImportError as exc:  # pragma: no cover - nur Hinweis für Nutzer
    print(f"Fehlendes Paket: {exc.name}\n"
          "Bitte installieren mit:  pip install -r requirements.txt")
    sys.exit(1)

APP_NAME = "SnapRec"
VERSION = "1.0.0"
CONFIG_PATH = Path.home() / ".snaprec.json"
COUNTDOWN_CHOICES = [0, 3, 5, 10]
FPS_CHOICES = [15, 24, 30, 60]
ACCENT = "#e81123"          # Rot für Aufnahme-Rahmen
SELECT_COLOR = "#4cc2ff"    # Blau wie beim Snipping Tool

IS_WINDOWS = sys.platform == "win32"
MSS = getattr(mss, "MSS", None) or mss.mss   # neuere mss-Versionen: mss.MSS


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------

def enable_dpi_awareness():
    """Unter Windows echte Pixel verwenden (sonst passt der Bereich bei
    Skalierung 125 %/150 % nicht zum aufgenommenen Bild)."""
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def exclude_from_capture(win):
    """Windows 10 (2004+) / 11: Fenster aus der Aufnahme ausblenden, damit
    Steuerleiste und Rahmen nie im Video landen."""
    if not IS_WINDOWS:
        return
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        WDA_EXCLUDEFROMCAPTURE = 0x11
        ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
    except Exception:
        pass


def default_output_dir():
    videos = Path.home() / "Videos"
    if not videos.exists():
        videos = Path.home()
    return str(videos / APP_NAME)


def load_config():
    cfg = {"countdown": 3, "fps": 30, "cursor": True, "output_dir": default_output_dir()}
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except OSError:
        pass


def open_path(path):
    """Datei oder Ordner mit dem Standardprogramm öffnen."""
    try:
        if IS_WINDOWS:
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as exc:
        messagebox.showerror(APP_NAME, f"Konnte nicht öffnen:\n{exc}")


def format_time(seconds):
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def virtual_screen():
    """Gesamte Fläche aller Monitore und die einzelnen Monitore."""
    with MSS() as sct:
        return dict(sct.monitors[0]), [dict(m) for m in sct.monitors[1:]]


def normalize_region(x1, y1, x2, y2):
    """Rechteck sortieren und auf gerade Breite/Höhe bringen (nötig für H.264)."""
    left, right = sorted((int(x1), int(x2)))
    top, bottom = sorted((int(y1), int(y2)))
    width = (right - left) // 2 * 2
    height = (bottom - top) // 2 * 2
    return {"left": left, "top": top, "width": width, "height": height}


# --------------------------------------------------------------------------
# Aufnahme (läuft in eigenem Thread)
# --------------------------------------------------------------------------

CURSOR_SHAPE = [(0, 0), (0, 17), (4, 13), (7, 20), (10, 19), (7, 12), (12, 12)]


def draw_cursor(img, x, y):
    if not (-20 <= x < img.width and -20 <= y < img.height):
        return
    pts = [(x + px, y + py) for px, py in CURSOR_SHAPE]
    draw = ImageDraw.Draw(img)
    draw.polygon(pts, fill="white", outline="black")


class Recorder(threading.Thread):
    """Nimmt den Bereich mit fester Bildrate auf und schreibt ein MP4.

    Ist der Rechner mal zu langsam, werden Bilder doppelt geschrieben, damit
    das Video trotzdem genauso lang ist wie die echte Aufnahme.
    """

    def __init__(self, region, fps, path, cursor_pos=None):
        super().__init__(daemon=True)
        self.region = region
        self.fps = fps
        self.path = path
        self.cursor_pos = cursor_pos  # Callable -> (x, y) oder None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self.error = None
        self.frames = 0
        self.elapsed = 0.0

    def stop(self):
        self._stop_event.set()

    def set_paused(self, paused):
        if paused:
            self._pause_event.set()
        else:
            self._pause_event.clear()

    @property
    def paused(self):
        return self._pause_event.is_set()

    def run(self):
        try:
            self._record()
        except Exception as exc:  # Fehler an die Oberfläche weiterreichen
            self.error = exc

    def _record(self):
        r = self.region
        size = (r["width"], r["height"])
        writer = imageio_ffmpeg.write_frames(
            self.path, size, fps=self.fps, codec="libx264", quality=None,
            macro_block_size=2, pix_fmt_in="rgb24", pix_fmt_out="yuv420p",
            output_params=["-crf", "20", "-preset", "veryfast", "-movflags", "+faststart"],
        )
        writer.send(None)
        interval = 1.0 / self.fps
        try:
            with MSS() as sct:
                start = time.perf_counter()
                paused_total = 0.0
                pause_began = None
                while not self._stop_event.is_set():
                    now = time.perf_counter()
                    if self._pause_event.is_set():
                        if pause_began is None:
                            pause_began = now
                        time.sleep(0.02)
                        continue
                    if pause_began is not None:
                        paused_total += now - pause_began
                        pause_began = None

                    shot = sct.grab(r)
                    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                    if self.cursor_pos:
                        pos = self.cursor_pos()
                        if pos:
                            draw_cursor(img, pos[0] - r["left"], pos[1] - r["top"])
                    data = img.tobytes()

                    self.elapsed = time.perf_counter() - start - paused_total
                    target = int(self.elapsed * self.fps) + 1
                    while self.frames < target:
                        writer.send(data)
                        self.frames += 1

                    next_time = start + paused_total + self.frames * interval
                    delay = next_time - time.perf_counter()
                    if delay > 0:
                        self._stop_event.wait(delay)
        finally:
            writer.close()


# --------------------------------------------------------------------------
# Graues Auswahl-Overlay (wie Snipping Tool)
# --------------------------------------------------------------------------

class SelectionOverlay(tk.Toplevel):
    """Zeigt einen abgedunkelten Screenshot aller Monitore; der aufgezogene
    Bereich wird hell dargestellt. Ergebnis geht an on_done(region|None)."""

    def __init__(self, master, on_done):
        super().__init__(master)
        self.on_done = on_done
        self.screen, self.monitors = virtual_screen()
        s = self.screen

        with MSS() as sct:
            shot = sct.grab(s)
        self.full = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        dark = ImageEnhance.Brightness(self.full).enhance(0.45)
        gray = Image.new("RGB", self.full.size, (40, 40, 40))
        dark = Image.blend(dark, gray, 0.25)

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.geometry(f"{s['width']}x{s['height']}+{s['left']}+{s['top']}")
        self.configure(cursor="crosshair", bg="black")

        self.canvas = tk.Canvas(self, width=s["width"], height=s["height"],
                                highlightthickness=0, bd=0, bg="black")
        self.canvas.pack(fill="both", expand=True)
        self._dark_tk = ImageTk.PhotoImage(dark)
        self.canvas.create_image(0, 0, image=self._dark_tk, anchor="nw")
        self._bright_tk = None
        self._bright_item = self.canvas.create_image(0, 0, anchor="nw")
        self._rect = self.canvas.create_rectangle(0, 0, 0, 0, outline=SELECT_COLOR,
                                                  width=2, state="hidden")
        self._label_bg = self.canvas.create_rectangle(0, 0, 0, 0, fill="#202020",
                                                      outline="", state="hidden")
        self._label = self.canvas.create_text(0, 0, fill="white", anchor="nw",
                                              font=("Segoe UI", 10), state="hidden")
        self._draw_hint()

        self._start = None
        self._pending_bright = None
        self._bright_job = None
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Double-Button-1>", self._whole_monitor)
        self.canvas.bind("<ButtonPress-3>", lambda e: self._finish(None))
        self.bind("<Escape>", lambda e: self._finish(None))
        self.bind("<Return>", self._whole_monitor)

        self.after(50, self._grab_focus)

    def _grab_focus(self):
        self.lift()
        self.focus_force()
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def _draw_hint(self):
        # Hinweis mittig oben auf dem Hauptmonitor
        m = self.monitors[0] if self.monitors else self.screen
        x = m["left"] - self.screen["left"] + m["width"] // 2
        y = m["top"] - self.screen["top"] + 40
        text = ("Bereich mit der Maus aufziehen   ·   Doppelklick/Enter = ganzer Monitor"
                "   ·   Esc = Abbrechen")
        t = self.canvas.create_text(x, y, text=text, fill="white", font=("Segoe UI", 12))
        x1, y1, x2, y2 = self.canvas.bbox(t)
        bg = self.canvas.create_rectangle(x1 - 16, y1 - 10, x2 + 16, y2 + 10,
                                          fill="#202020", outline="#555555")
        self.canvas.tag_lower(bg, t)
        self._hint_items = (t, bg)

    def _to_screen(self, cx, cy):
        return cx + self.screen["left"], cy + self.screen["top"]

    def _press(self, event):
        self._start = (event.x, event.y)
        for item in self._hint_items:
            self.canvas.itemconfigure(item, state="hidden")

    def _drag(self, event):
        if not self._start:
            return
        x1, y1 = self._start
        x2 = min(max(event.x, 0), self.screen["width"])
        y2 = min(max(event.y, 0), self.screen["height"])
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        self.canvas.coords(self._rect, left, top, right, bottom)
        self.canvas.itemconfigure(self._rect, state="normal")

        # heller Ausschnitt – nur einmal pro Leerlauf neu zeichnen, damit das
        # Ziehen flüssig bleibt und trotzdem die letzte Position stimmt
        self._pending_bright = (left, top, right, bottom)
        if not self._bright_job:
            self._bright_job = self.after_idle(self._render_bright)
        self.canvas.tag_raise(self._rect)

        label = f"{(right - left) // 2 * 2} × {(bottom - top) // 2 * 2}"
        ly = top - 26 if top > 30 else bottom + 6
        self.canvas.itemconfigure(self._label, text=label, state="normal")
        self.canvas.coords(self._label, left + 6, ly + 3)
        bx1, by1, bx2, by2 = self.canvas.bbox(self._label)
        self.canvas.coords(self._label_bg, bx1 - 6, by1 - 3, bx2 + 6, by2 + 3)
        self.canvas.itemconfigure(self._label_bg, state="normal")
        self.canvas.tag_raise(self._label_bg)
        self.canvas.tag_raise(self._label)

    def _render_bright(self):
        self._bright_job = None
        left, top, right, bottom = self._pending_bright
        if right - left < 2 or bottom - top < 2:
            self.canvas.itemconfigure(self._bright_item, image="")
            return
        crop = self.full.crop((left, top, right, bottom))
        self._bright_tk = ImageTk.PhotoImage(crop)
        self.canvas.itemconfigure(self._bright_item, image=self._bright_tk)
        self.canvas.coords(self._bright_item, left, top)

    def _release(self, event):
        if not self._start:
            return
        x1, y1 = self._to_screen(*self._start)
        ex = min(max(event.x, 0), self.screen["width"])
        ey = min(max(event.y, 0), self.screen["height"])
        x2, y2 = self._to_screen(ex, ey)
        self._start = None
        region = normalize_region(x1, y1, x2, y2)
        if region["width"] < 16 or region["height"] < 16:
            # zu klein – vermutlich nur ein Klick: nochmal versuchen
            for item in (self._rect, self._label, self._label_bg):
                self.canvas.itemconfigure(item, state="hidden")
            self.canvas.itemconfigure(self._bright_item, image="")
            return
        self._finish(region)

    def _whole_monitor(self, event=None):
        px, py = self.winfo_pointerxy()
        for m in self.monitors:
            if m["left"] <= px < m["left"] + m["width"] and m["top"] <= py < m["top"] + m["height"]:
                break
        else:
            m = self.monitors[0] if self.monitors else self.screen
        self._finish(normalize_region(m["left"], m["top"],
                                      m["left"] + m["width"], m["top"] + m["height"]))

    def _finish(self, region):
        if self._bright_job:
            self.after_cancel(self._bright_job)
            self._bright_job = None
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        self.on_done(region)


# --------------------------------------------------------------------------
# Countdown, Rahmen und Steuerleiste
# --------------------------------------------------------------------------

class RegionFrame:
    """Roter/blauer Rahmen, der AUSSERHALB des Bereichs liegt und so nicht
    mit aufgenommen wird."""

    def __init__(self, master, region, color, thickness=3):
        self.wins = []
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

    def set_color(self, color):
        for win in self.wins:
            win.configure(bg=color)

    def destroy(self):
        for win in self.wins:
            win.destroy()
        self.wins = []


class Countdown(tk.Toplevel):
    """Große Zahl mittig über dem Bereich. Esc bricht ab."""

    def __init__(self, master, region, seconds, on_done):
        super().__init__(master)
        self.on_done = on_done
        self.remaining = seconds
        self._job = None
        size = 180
        x = region["left"] + region["width"] // 2 - size // 2
        y = region["top"] + region["height"] // 2 - size // 2
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 0.85)
        except tk.TclError:
            pass
        self.configure(bg="#202020")
        self.geometry(f"{size}x{size}+{x}+{y}")
        self.canvas = tk.Canvas(self, width=size, height=size, bg="#202020",
                                highlightthickness=0)
        self.canvas.pack()
        self.canvas.create_oval(10, 10, size - 10, size - 10, outline=SELECT_COLOR, width=4)
        self.text = self.canvas.create_text(size // 2, size // 2 - 8, fill="white",
                                            font=("Segoe UI", 64, "bold"))
        self.canvas.create_text(size // 2, size - 36, fill="#bbbbbb",
                                text="Esc = Abbrechen", font=("Segoe UI", 9))
        self.bind("<Escape>", lambda e: self._finish(False))
        self.canvas.bind("<Button-1>", lambda e: self._finish(True))  # Klick = sofort
        self.after(30, self.focus_force)
        self._tick()

    def _tick(self):
        if self.remaining <= 0:
            self._finish(True)
            return
        self.canvas.itemconfigure(self.text, text=str(self.remaining))
        self.remaining -= 1
        self._job = self.after(1000, self._tick)

    def _finish(self, go):
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        if not self.winfo_exists():
            return
        self.destroy()
        self.on_done(go)


class ControlBar(tk.Toplevel):
    """Kleine Leiste mit Zeit, Pause und Stopp – sitzt unter/über dem Bereich."""

    def __init__(self, master, region, on_pause, on_stop):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#202020", highlightthickness=1, highlightbackground="#555555")

        self.dot = tk.Label(self, text="●", fg=ACCENT, bg="#202020", font=("Segoe UI", 12))
        self.dot.pack(side="left", padx=(10, 4), pady=4)
        self.time = tk.Label(self, text="00:00", fg="white", bg="#202020",
                             font=("Consolas", 12, "bold"))
        self.time.pack(side="left", padx=(0, 10))
        btn = dict(bg="#333333", fg="white", activebackground="#444444",
                   activeforeground="white", relief="flat", bd=0,
                   font=("Segoe UI", 10), padx=10, pady=3, cursor="hand2")
        self.pause_btn = tk.Button(self, text="⏸ Pause", command=on_pause, **btn)
        self.pause_btn.pack(side="left", padx=2, pady=4)
        stop = dict(btn, bg=ACCENT, activebackground="#c50f1f")
        tk.Button(self, text="■ Stopp", command=on_stop, **stop).pack(side="left", padx=(2, 6), pady=4)

        self.update_idletasks()
        bw, bh = self.winfo_reqwidth(), self.winfo_reqheight()
        screen, _ = virtual_screen()
        x = region["left"] + region["width"] // 2 - bw // 2
        x = max(screen["left"], min(x, screen["left"] + screen["width"] - bw))
        below = region["top"] + region["height"] + 10
        above = region["top"] - bh - 10
        if below + bh <= screen["top"] + screen["height"]:
            y = below
        elif above >= screen["top"]:
            y = above
        else:  # Bereich ist so groß wie der Bildschirm -> unten innen
            y = region["top"] + region["height"] - bh - 20
        self.geometry(f"+{x}+{y}")
        exclude_from_capture(self)

        # Leiste mit der Maus verschiebbar
        for w in (self, self.dot, self.time):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)

    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.winfo_x(), e.y_root - self.winfo_y()

    def _drag_move(self, e):
        self.geometry(f"+{e.x_root - self._dx}+{e.y_root - self._dy}")

    def update_state(self, elapsed, paused):
        self.time.configure(text=format_time(elapsed))
        self.pause_btn.configure(text="▶ Weiter" if paused else "⏸ Pause")
        blink = paused or int(elapsed * 2) % 2 == 0
        self.dot.configure(fg=("#f7b500" if paused else ACCENT) if blink else "#202020")


# --------------------------------------------------------------------------
# Hauptfenster
# --------------------------------------------------------------------------

class App:
    def __init__(self, root, cfg):
        self.root = root
        self.cfg = cfg
        self.recorder = None
        self.frame = None
        self.bar = None
        self.last_file = None
        self._cursor = None
        self._region = None

        root.title(APP_NAME)
        root.resizable(False, False)
        root.attributes("-topmost", True)
        self._build_ui()
        root.bind("<Control-n>", lambda e: self.new_recording())
        root.protocol("WM_DELETE_WINDOW", self.quit)

    # ---- Oberfläche ------------------------------------------------------
    def _build_ui(self):
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")

        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")

        self.new_btn = ttk.Button(top, text="＋ Neue Aufnahme", command=self.new_recording)
        self.new_btn.grid(row=0, column=0, rowspan=2, padx=(0, 12), ipady=6)

        ttk.Label(top, text="Countdown").grid(row=0, column=1, sticky="w")
        self.countdown_var = tk.StringVar(value=self._countdown_text(self.cfg["countdown"]))
        cd = ttk.Combobox(top, textvariable=self.countdown_var, width=11, state="readonly",
                          values=[self._countdown_text(c) for c in COUNTDOWN_CHOICES])
        cd.grid(row=1, column=1, padx=(0, 8))
        cd.bind("<<ComboboxSelected>>", lambda e: self._save())

        ttk.Label(top, text="Bilder/Sek.").grid(row=0, column=2, sticky="w")
        self.fps_var = tk.StringVar(value=str(self.cfg["fps"]))
        fps = ttk.Combobox(top, textvariable=self.fps_var, width=5, state="readonly",
                           values=[str(f) for f in FPS_CHOICES])
        fps.grid(row=1, column=2, padx=(0, 8))
        fps.bind("<<ComboboxSelected>>", lambda e: self._save())

        self.cursor_var = tk.BooleanVar(value=self.cfg["cursor"])
        ttk.Checkbutton(top, text="Mauszeiger", variable=self.cursor_var,
                        command=self._save).grid(row=1, column=3, padx=(0, 8))

        ttk.Button(top, text="📁", width=3, command=self.choose_folder).grid(row=1, column=4)

        bottom = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        bottom.pack(fill="x")
        self.status = ttk.Label(bottom, text="Bereit – Strg+N für eine neue Aufnahme",
                                foreground="#666666")
        self.status.pack(side="left")
        self.play_btn = ttk.Button(bottom, text="▶ Abspielen", command=self.play_last)
        self.folder_btn = ttk.Button(bottom, text="Ordner öffnen",
                                     command=lambda: open_path(self.cfg["output_dir"]))

    @staticmethod
    def _countdown_text(sec):
        return "Kein" if sec == 0 else f"{sec} Sekunden"

    def _save(self):
        text = self.countdown_var.get()
        self.cfg["countdown"] = 0 if text == "Kein" else int(text.split()[0])
        self.cfg["fps"] = int(self.fps_var.get())
        self.cfg["cursor"] = bool(self.cursor_var.get())
        save_config(self.cfg)

    def set_status(self, text, done=False):
        self.status.configure(text=text)
        if done:
            self.folder_btn.pack(side="right", padx=(6, 0))
            self.play_btn.pack(side="right")
        else:
            self.play_btn.pack_forget()
            self.folder_btn.pack_forget()

    def choose_folder(self):
        folder = filedialog.askdirectory(initialdir=self.cfg["output_dir"],
                                         title="Speicherort für Aufnahmen")
        if folder:
            self.cfg["output_dir"] = folder
            save_config(self.cfg)
            self.set_status(f"Speicherort: {folder}")

    def play_last(self):
        if self.last_file:
            open_path(self.last_file)

    # ---- Ablauf ----------------------------------------------------------
    def new_recording(self):
        if self.recorder:
            return
        self._save()
        self.root.withdraw()
        # kurz warten, bis das Fenster wirklich weg ist, dann Screenshot
        self.root.after(250, lambda: SelectionOverlay(self.root, self._on_selected))

    def _on_selected(self, region):
        if not region:
            self._back_to_main("Abgebrochen")
            return
        self._region = region
        self.frame = RegionFrame(self.root, region, SELECT_COLOR)
        if self.cfg["countdown"] > 0:
            Countdown(self.root, region, self.cfg["countdown"], self._after_countdown)
        else:
            self._after_countdown(True)

    def _after_countdown(self, go):
        if not go:
            self._cleanup_windows()
            self._back_to_main("Abgebrochen")
            return
        # Countdown-Fenster ist zu – kurz warten, damit es nicht im Video landet
        self.root.after(120, self._start_recording)

    def _start_recording(self):
        out_dir = Path(self.cfg["output_dir"])
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._cleanup_windows()
            messagebox.showerror(APP_NAME, f"Ordner kann nicht angelegt werden:\n{exc}")
            self._back_to_main("Fehler")
            return
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = str(out_dir / f"Aufnahme_{stamp}.mp4")

        self.frame.set_color(ACCENT)
        self.bar = ControlBar(self.root, self._region, self.toggle_pause, self.stop_recording)
        cursor = self._get_cursor if self.cfg["cursor"] else None
        self.recorder = Recorder(self._region, self.cfg["fps"], path, cursor)
        self._track_cursor()
        self.recorder.start()
        self._update_bar()

    def _track_cursor(self):
        """Mausposition im Hauptthread lesen (Tk ist nicht threadsicher)."""
        if not self.recorder:
            return
        try:
            self._cursor = self.root.winfo_pointerxy()
        except tk.TclError:
            self._cursor = None
        self.root.after(15, self._track_cursor)

    def _get_cursor(self):
        return self._cursor

    def _update_bar(self):
        rec = self.recorder
        if not rec:
            return
        if rec.error or not rec.is_alive():
            self.stop_recording()
            return
        self.bar.update_state(rec.elapsed, rec.paused)
        self.root.after(200, self._update_bar)

    def toggle_pause(self):
        if self.recorder:
            self.recorder.set_paused(not self.recorder.paused)
            self.frame.set_color("#f7b500" if self.recorder.paused else ACCENT)
            self.bar.update_state(self.recorder.elapsed, self.recorder.paused)

    def stop_recording(self):
        rec = self.recorder
        if not rec:
            return
        rec.stop()
        self._cleanup_windows()
        self.set_status("Video wird gespeichert …")
        self.root.deiconify()

        def wait():
            if rec.is_alive():
                self.root.after(100, wait)
                return
            self.recorder = None
            if rec.error:
                messagebox.showerror(APP_NAME, f"Aufnahme fehlgeschlagen:\n{rec.error}")
                self._back_to_main("Fehler bei der Aufnahme")
            else:
                self.last_file = rec.path
                self._back_to_main(f"Gespeichert: {Path(rec.path).name} "
                                   f"({format_time(rec.elapsed)})", done=True)
        wait()

    def _cleanup_windows(self):
        if self.bar:
            self.bar.destroy()
            self.bar = None
        if self.frame:
            self.frame.destroy()
            self.frame = None

    def _back_to_main(self, text, done=False):
        self.root.deiconify()
        self.root.lift()
        self.set_status(text, done)

    def quit(self):
        if self.recorder:
            self.recorder.stop()
            self.recorder.join(timeout=10)
        self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description=f"{APP_NAME} – Bildschirmbereich aufnehmen")
    parser.add_argument("-c", "--countdown", type=int, help="Countdown in Sekunden (0 = keiner)")
    parser.add_argument("--fps", type=int, help="Bilder pro Sekunde (Standard 30)")
    parser.add_argument("-o", "--output", help="Ordner für die Videos")
    parser.add_argument("--no-cursor", action="store_true", help="Mauszeiger nicht aufnehmen")
    parser.add_argument("-s", "--start", action="store_true",
                        help="direkt mit der Bereichsauswahl starten")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    args = parser.parse_args(argv)

    cfg = load_config()
    if args.countdown is not None:
        cfg["countdown"] = max(0, args.countdown)
    if args.fps:
        cfg["fps"] = max(1, min(args.fps, 120))
    if args.output:
        cfg["output_dir"] = args.output
    if args.no_cursor:
        cfg["cursor"] = False
    if cfg["countdown"] not in COUNTDOWN_CHOICES:
        COUNTDOWN_CHOICES.append(cfg["countdown"])
        COUNTDOWN_CHOICES.sort()
    if cfg["fps"] not in FPS_CHOICES:
        FPS_CHOICES.append(cfg["fps"])
        FPS_CHOICES.sort()

    enable_dpi_awareness()
    root = tk.Tk()
    app = App(root, cfg)
    if args.start:
        root.after(300, app.new_recording)
    root.mainloop()


if __name__ == "__main__":
    main()
