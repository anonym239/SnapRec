"""„Meine Aufnahmen“: alle Videos ansehen, abspielen und löschen."""

import datetime
import io
import os
import queue
import re
import subprocess
import threading
import tkinter as tk
from pathlib import Path

import customtkinter as ctk
import imageio_ffmpeg
from PIL import Image

from snaprec import APP_NAME, theme
from snaprec.utils import IS_WINDOWS, format_size, format_time, open_path, set_alpha

THUMB = (128, 72)


def font(size, weight="normal"):
    return ctk.CTkFont(theme.FONT, size, weight)


def list_recordings(folder):
    """Alle MP4-Dateien im Ordner, neueste zuerst."""
    try:
        files = [p for p in Path(folder).iterdir()
                 if p.suffix.lower() == ".mp4" and p.is_file() and not p.name.startswith(".")]
    except OSError:
        return []
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def delete_recording(path):
    """In den Papierkorb verschieben (wenn möglich), sonst endgültig löschen.
    Gibt True zurück, wenn im Papierkorb gelandet."""
    try:
        from send2trash import send2trash
        send2trash(str(path))
        return True
    except ImportError:
        pass
    except Exception:
        if not os.path.exists(path):
            return True
    os.remove(path)
    return False


def probe(path):
    """(Dauer in Sekunden oder None, Vorschaubild oder None) per ffmpeg."""
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-ss", "0.3", "-i", str(path),
           "-frames:v", "1", "-vf",
           f"scale={THUMB[0]}:{THUMB[1]}:force_original_aspect_ratio=decrease,"
           f"pad={THUMB[0]}:{THUMB[1]}:(ow-iw)/2:(oh-ih)/2:color=black",
           "-f", "image2pipe", "-vcodec", "png", "-"]
    kwargs = {"creationflags": 0x08000000} if IS_WINDOWS else {}
    try:
        res = subprocess.run(cmd, capture_output=True, timeout=15, **kwargs)
    except Exception:
        return None, None
    duration = None
    m = re.search(rb"Duration: (\d+):(\d+):(\d+\.\d+)", res.stderr)
    if m:
        duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    thumb = None
    if res.stdout:
        try:
            thumb = Image.open(io.BytesIO(res.stdout)).convert("RGB")
        except Exception:
            thumb = None
    return duration, thumb


def confirm(master, title, text, ok_text="Löschen"):
    """Moderner Ja/Nein-Dialog. Gibt True bei Bestätigung zurück."""
    win = ctk.CTkToplevel(master, fg_color=theme.BG)
    win.title(APP_NAME)
    win.resizable(False, False)
    win.attributes("-topmost", True)
    win.transient(master)
    result = {"ok": False}
    body = ctk.CTkFrame(win, fg_color="transparent")
    body.pack(padx=24, pady=(22, 10), fill="both")
    ctk.CTkLabel(body, text="", image=theme.ctk_icon("trash", 30, theme.REC)).pack(anchor="w")
    ctk.CTkLabel(body, text=title, font=font(17, "bold"), text_color=theme.TEXT,
                 anchor="w").pack(fill="x", pady=(10, 4))
    ctk.CTkLabel(body, text=text, font=font(12), text_color=theme.MUTED, anchor="w",
                 justify="left", wraplength=340).pack(fill="x")
    btns = ctk.CTkFrame(win, fg_color="transparent")
    btns.pack(fill="x", padx=24, pady=(10, 20))

    def done(ok):
        result["ok"] = ok
        win.grab_release()
        win.destroy()

    ctk.CTkButton(btns, text=ok_text, height=38, corner_radius=12, font=font(13, "bold"),
                  fg_color=theme.REC, hover_color=theme.REC_HOVER,
                  command=lambda: done(True)).pack(side="right")
    ctk.CTkButton(btns, text="Abbrechen", height=38, corner_radius=12, font=font(13),
                  fg_color=theme.SURFACE_2, hover_color=theme.SURFACE_3,
                  command=lambda: done(False)).pack(side="right", padx=(0, 8))
    win.bind("<Escape>", lambda e: done(False))
    win.bind("<Return>", lambda e: done(True))
    win.protocol("WM_DELETE_WINDOW", lambda: done(False))
    win.update_idletasks()
    x = master.winfo_rootx() + master.winfo_width() // 2 - win.winfo_reqwidth() // 2
    y = master.winfo_rooty() + master.winfo_height() // 2 - win.winfo_reqheight() // 2
    win.wm_geometry(f"+{max(0, x)}+{max(0, y)}")
    win.after(30, win.focus_force)
    try:
        win.grab_set()
    except tk.TclError:
        pass
    master.wait_window(win)
    return result["ok"]


class RecordingRow(ctk.CTkFrame):
    def __init__(self, window, master, path):
        super().__init__(master, fg_color=theme.SURFACE, corner_radius=14, border_width=1,
                         border_color=theme.BORDER)
        self.window = window
        self.path = path
        self.selected = tk.BooleanVar(value=False)

        self.check = ctk.CTkCheckBox(self, text="", width=24, checkbox_width=20, checkbox_height=20,
                                     corner_radius=6, border_width=2, fg_color=theme.ACCENT,
                                     hover_color=theme.ACCENT_HOVER, border_color=theme.SURFACE_3,
                                     variable=self.selected, command=window.update_selection)
        self.check.pack(side="left", padx=(12, 4))
        placeholder = Image.new("RGB", THUMB, theme.hex_to_rgb(theme.SURFACE_2))
        self.thumb = ctk.CTkLabel(self, text="", image=self._ctk_image(placeholder), cursor="hand2")
        self.thumb.pack(side="left", padx=6, pady=10)
        self.thumb.bind("<Button-1>", lambda e: self.play())

        texts = ctk.CTkFrame(self, fg_color="transparent")
        texts.pack(side="left", fill="x", expand=True, padx=8)
        ctk.CTkLabel(texts, text=path.name, font=font(13, "bold"), text_color=theme.TEXT,
                     anchor="w").pack(fill="x")
        stat = path.stat()
        when = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%d.%m.%Y, %H:%M")
        self.meta_base = f"{when}  ·  {format_size(stat.st_size)}"
        self.meta = ctk.CTkLabel(texts, text=self.meta_base, font=font(11), text_color=theme.MUTED,
                                 anchor="w")
        self.meta.pack(fill="x")

        icon_btn = dict(text="", width=36, height=36, corner_radius=10, fg_color=theme.SURFACE_2)
        ctk.CTkButton(self, image=theme.ctk_icon("trash", 16, theme.REC), hover_color="#3a1f27",
                      command=self.delete, **icon_btn).pack(side="right", padx=(4, 12))
        ctk.CTkButton(self, image=theme.ctk_icon("play", 14), hover_color=theme.SURFACE_3,
                      command=self.play, **icon_btn).pack(side="right", padx=4)

    @staticmethod
    def _ctk_image(img):
        return ctk.CTkImage(light_image=img, dark_image=img, size=THUMB)

    def set_info(self, duration, thumb):
        if duration is not None:
            self.meta.configure(text=f"{format_time(duration)}  ·  {self.meta_base}")
        if thumb is not None:
            self.thumb.configure(image=self._ctk_image(thumb))

    def play(self):
        try:
            open_path(str(self.path))
        except Exception as exc:
            self.window.show_error(f"Konnte nicht abspielen: {exc}")

    def delete(self):
        self.window.delete_paths([self.path])


class LibraryWindow(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app.root, fg_color=theme.BG)
        self.app = app
        self.title(f"{APP_NAME} – Meine Aufnahmen")
        self.attributes("-topmost", True)
        self.geometry("620x560")
        self.minsize(520, 360)
        app.apply_icon(self)
        self.rows = {}
        self._queue = queue.Queue()
        self._closed = False

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.pack(fill="x", padx=20, pady=(18, 6))
        ctk.CTkLabel(head, text="Meine Aufnahmen", font=font(22, "bold"),
                     text_color=theme.TEXT).pack(side="left")
        ctk.CTkButton(head, text=" Ordner", image=theme.ctk_icon("folder", 14), width=90, height=34,
                      corner_radius=10, font=font(12), fg_color=theme.SURFACE_2,
                      hover_color=theme.SURFACE_3,
                      command=lambda: app._open(app.cfg["output_dir"])).pack(side="right")

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=20, pady=(0, 8))
        self.count = ctk.CTkLabel(bar, text="", font=font(12), text_color=theme.MUTED)
        self.count.pack(side="left")
        self.delete_selected_btn = ctk.CTkButton(
            bar, text=" Auswahl löschen", image=theme.ctk_icon("trash", 14, "#ffffff"), height=32,
            corner_radius=10, font=font(12, "bold"), fg_color=theme.REC, hover_color=theme.REC_HOVER,
            command=self._delete_selected)
        self.select_all_btn = ctk.CTkButton(
            bar, text="Alle auswählen", height=32, width=110, corner_radius=10, font=font(12),
            fg_color="transparent", hover_color=theme.SURFACE_2, text_color=theme.ACCENT,
            command=self._toggle_all)
        self.select_all_btn.pack(side="right")

        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                           scrollbar_button_color=theme.SURFACE_3,
                                           scrollbar_button_hover_color=theme.BORDER)
        self.list.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.empty = ctk.CTkLabel(self.list, text="Noch keine Aufnahmen.\nStarte mit „Neue Aufnahme“.",
                                  font=font(13), text_color=theme.MUTED, justify="center")
        self.error = ctk.CTkLabel(self, text="", font=font(11), text_color=theme.REC)

        self.bind("<Delete>", lambda e: self._delete_selected())
        self.bind("<F5>", lambda e: self.refresh())
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh()
        self._poll()
        set_alpha(self, 0.0)
        theme.animate(self, 200, lambda t: set_alpha(self, t))
        self.after(60, self.focus_force)

    # ---- Liste ----------------------------------------------------------------
    def refresh(self):
        for row in self.rows.values():
            row.destroy()
        self.rows = {}
        files = list_recordings(self.app.cfg["output_dir"])
        if files:
            self.empty.pack_forget()
        else:
            self.empty.pack(pady=60)
        for path in files:
            row = RecordingRow(self, self.list, path)
            row.pack(fill="x", padx=8, pady=5)
            self.rows[path] = row
        self.update_selection()
        threading.Thread(target=self._load_infos, args=(list(files),), daemon=True).start()

    def _load_infos(self, files):
        for path in files:
            if self._closed:
                return
            self._queue.put((path, *probe(path)))

    def _poll(self):
        if self._closed:
            return
        try:
            while True:
                path, duration, thumb = self._queue.get_nowait()
                row = self.rows.get(path)
                if row and row.winfo_exists():
                    row.set_info(duration, thumb)
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def selected_paths(self):
        return [p for p, r in self.rows.items() if r.selected.get()]

    def update_selection(self):
        n_sel, n = len(self.selected_paths()), len(self.rows)
        total = sum(p.stat().st_size for p in self.rows if p.exists())
        if n_sel:
            self.count.configure(text=f"{n_sel} von {n} ausgewählt")
            self.delete_selected_btn.pack(side="right", padx=(8, 0))
        else:
            word = "Aufnahme" if n == 1 else "Aufnahmen"
            self.count.configure(text=f"{n} {word}  ·  {format_size(total)}" if n else "")
            self.delete_selected_btn.pack_forget()
        self.select_all_btn.configure(text="Auswahl aufheben" if n and n_sel == n else "Alle auswählen")

    def _toggle_all(self):
        value = len(self.selected_paths()) != len(self.rows)
        for row in self.rows.values():
            row.selected.set(value)
        self.update_selection()

    # ---- Löschen ----------------------------------------------------------------
    def _delete_selected(self):
        paths = self.selected_paths()
        if paths:
            self.delete_paths(paths)

    def delete_paths(self, paths):
        if len(paths) == 1:
            title, text = "Aufnahme löschen?", f"„{paths[0].name}“ wird in den Papierkorb verschoben."
        else:
            title, text = f"{len(paths)} Aufnahmen löschen?", "Die Videos werden in den Papierkorb verschoben."
        if not confirm(self, title, text):
            return
        failed = []
        for path in paths:
            try:
                delete_recording(path)
                self.app.on_recording_deleted(path)
            except OSError as exc:
                failed.append(f"{path.name}: {exc.strerror or exc}")
        for path in paths:
            row = self.rows.get(path)
            if row and not path.exists():
                self._remove_row(path, row)
        if failed:
            self.show_error("Nicht gelöscht (evtl. noch geöffnet?): " + "; ".join(failed))
        self.update_selection()
        if not self.rows:
            self.empty.pack(pady=60)

    def _remove_row(self, path, row):
        del self.rows[path]
        row.destroy()

    def show_error(self, text):
        self.error.configure(text=text)
        self.error.pack(fill="x", padx=20, pady=(0, 10))
        self.after(6000, lambda: self.error.winfo_exists() and self.error.pack_forget())

    def close(self):
        self._closed = True
        self.app.library_window = None
        self.destroy()
