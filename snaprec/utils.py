"""Hilfsfunktionen: Einstellungen, Bildschirme, Windows-Extras."""

import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path

import mss

from snaprec import APP_NAME

IS_WINDOWS = sys.platform == "win32"
MSS = getattr(mss, "MSS", None) or mss.mss   # neuere mss-Versionen: mss.MSS
CONFIG_PATH = Path.home() / ".snaprec.json"

DEFAULT_HOTKEYS = {
    "toggle": "ctrl+alt+r",       # Aufnahme starten / stoppen
    "pause": "ctrl+alt+p",        # Pause / Weiter
    "fullscreen": "ctrl+alt+f",   # ganzen Bildschirm aufnehmen
    "library": "",                # Meine Aufnahmen öffnen (standardmäßig aus)
}


def default_output_dir():
    videos = Path.home() / "Videos"
    if not videos.exists():
        videos = Path.home()
    return str(videos / APP_NAME)


def default_config():
    return {
        "countdown": 3,
        "fps": 30,
        "cursor": True,
        "resolution": "1080p",
        "audio_system": False,
        "audio_mic": False,
        "output_dir": default_output_dir(),
        "hotkeys": dict(DEFAULT_HOTKEYS),
        "intro_seen": False,
    }


def load_config(path=CONFIG_PATH):
    cfg = default_config()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            hotkeys = data.pop("hotkeys", None)
            cfg.update(data)
            if isinstance(hotkeys, dict):
                cfg["hotkeys"].update({k: v for k, v in hotkeys.items() if k in DEFAULT_HOTKEYS})
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg, path=CONFIG_PATH):
    try:
        Path(path).write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def open_path(path):
    """Datei oder Ordner mit dem Standardprogramm öffnen."""
    if IS_WINDOWS:
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def format_time(seconds):
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def format_size(num_bytes):
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            text = f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
            return text.replace(".", ",")
        size /= 1024
    return ""


def short_path(path, max_len=38):
    home = str(Path.home())
    if path.startswith(home):
        path = "~" + path[len(home):]
    if len(path) > max_len:
        path = "…" + path[-(max_len - 1):]
    return path


def virtual_screen():
    """Gesamte Fläche aller Monitore und die einzelnen Monitore."""
    with MSS() as sct:
        return dict(sct.monitors[0]), [dict(m) for m in sct.monitors[1:]]


def monitor_at(x, y, monitors):
    for m in monitors:
        if m["left"] <= x < m["left"] + m["width"] and m["top"] <= y < m["top"] + m["height"]:
            return m
    return monitors[0]


def normalize_region(x1, y1, x2, y2):
    """Rechteck sortieren und auf gerade Breite/Höhe bringen (nötig für H.264)."""
    left, right = sorted((int(x1), int(x2)))
    top, bottom = sorted((int(y1), int(y2)))
    width = (right - left) // 2 * 2
    height = (bottom - top) // 2 * 2
    return {"left": left, "top": top, "width": width, "height": height}


# ---- Windows-Extras ------------------------------------------------------

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


def _hwnd(win):
    win.update_idletasks()
    return ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()


def exclude_from_capture(win):
    """Windows 10 (2004+) / 11: Fenster aus der Aufnahme ausblenden, damit
    Steuerleiste und Rahmen nie im Video landen."""
    if not IS_WINDOWS:
        return
    try:
        WDA_EXCLUDEFROMCAPTURE = 0x11
        ctypes.windll.user32.SetWindowDisplayAffinity(_hwnd(win), WDA_EXCLUDEFROMCAPTURE)
    except Exception:
        pass


def round_corners(win):
    """Windows 11: abgerundete Fensterecken auch für rahmenlose Fenster."""
    if not IS_WINDOWS:
        return
    try:
        DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, 2
        value = ctypes.c_int(DWMWCP_ROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            _hwnd(win), DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


def set_alpha(win, alpha):
    try:
        win.attributes("-alpha", alpha)
    except Exception:
        pass
