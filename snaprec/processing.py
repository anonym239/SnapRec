"""Smarte Nachbearbeitung: Video analysieren, auf 1080p / 1440p / 4K
hochskalieren und den Ton einmischen – mit Fortschritt für den Ladebildschirm.

Die Aufnahme wird zuerst in Originalgröße (fast verlustfrei, volle
Farbauflösung) gespeichert. Danach wählt SnapRec je nach Inhalt die beste
Methode:

* Bildschirm-Inhalt (Text, Fenster, Knöpfe): xBR-Kantenvergrößerung +
  Lanczos + kontrastadaptive Schärfung (CAS) – Schrift bleibt knackig.
* Video/Foto-Inhalt: leichtes Entrauschen der Kompressionsartefakte +
  Lanczos + CAS.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache

import imageio_ffmpeg
from PIL import Image, ImageChops, ImageFilter, ImageStat

from snaprec.audio import SAMPLE_RATE

IS_WINDOWS = sys.platform == "win32"

# Ziel-Auflösungen (quer); hochkant wird Breite/Höhe getauscht
TARGETS = {"1080p": (1920, 1080), "1440p": (2560, 1440), "4k": (3840, 2160)}
RESOLUTION_LABELS = {"original": "Original", "1080p": "1080p", "1440p": "1440p", "4k": "4K"}


def _popen_kwargs():
    return {"creationflags": 0x08000000} if IS_WINDOWS else {}  # kein Konsolenfenster


def output_size(width, height, resolution):
    """Größe des fertigen Videos. Hochkant-Bereiche werden hochkant ausgegeben."""
    target = TARGETS.get(resolution)
    if not target:
        return width // 2 * 2, height // 2 * 2
    return target if width >= height else (target[1], target[0])


def upscale_factor(width, height, resolution):
    """> 1, wenn der Bereich kleiner ist als das Ziel und vergrößert wird."""
    w, h = output_size(width, height, resolution)
    return min(w / max(1, width), h / max(1, height))


@lru_cache(maxsize=1)
def available_filters():
    try:
        out = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-filters"],
                             capture_output=True, text=True, timeout=20, **_popen_kwargs()).stdout
    except Exception:
        return frozenset()
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3 and "->" in parts[2]:
            names.add(parts[1])
    return frozenset(names)


# ---- Analyse -------------------------------------------------------------

@dataclass
class Analysis:
    content: str = "screen"        # "screen" (Text/Oberflächen) oder "video"
    sharpness: float = 0.0         # Varianz des Laplace-Filters (höher = schärfer)
    flat: float = 0.0              # Anteil einfarbiger Flächen
    colors: float = 0.0            # Farbvielfalt 0..1
    motion: float = 0.0            # mittlere Veränderung zwischen den Bildern
    frames: int = 0

    @property
    def blurry(self):
        return self.sharpness < 180

    @property
    def short(self):
        return "Bildschirm-Inhalt" if self.content == "screen" else "Video-Inhalt"

    @property
    def label(self):
        return "Bildschirm-Inhalt (Text & Oberflächen)" if self.content == "screen" else "Video- / Foto-Inhalt"


_LAPLACE = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128)


def analyze_images(images):
    """Kennzahlen aus einigen Beispielbildern berechnen."""
    result = Analysis(frames=len(images))
    if not images:
        return result
    sharp, flat, colors, motion = [], [], [], []
    prev = None
    for img in images:
        img = img.convert("RGB")
        img.thumbnail((640, 640))
        gray = img.convert("L")
        sharp.append(ImageStat.Stat(gray.filter(_LAPLACE)).var[0])
        edges = gray.filter(ImageFilter.FIND_EDGES)
        hist = edges.histogram()
        flat.append(sum(hist[:6]) / max(1, sum(hist)))
        small = img.resize((128, 72))
        colors.append(len(small.getcolors(maxcolors=128 * 72) or []) / (128 * 72))
        if prev is not None and prev.size == gray.size:
            motion.append(ImageStat.Stat(ImageChops.difference(prev, gray)).mean[0])
        prev = gray
    result.sharpness = sum(sharp) / len(sharp)
    result.flat = sum(flat) / len(flat)
    result.colors = sum(colors) / len(colors)
    result.motion = sum(motion) / len(motion) if motion else 0.0
    # Oberflächen: viele glatte Flächen und wenige Farben; Videos/Fotos: viele Farbtöne
    if result.colors < 0.2 and result.flat > 0.5:
        result.content = "screen"
    elif result.colors > 0.35:
        result.content = "video"
    else:
        result.content = "screen" if result.flat > 0.7 else "video"
    return result


def sample_frames(path, duration, count=6):
    """Einige Bilder gleichmäßig verteilt aus dem Video holen."""
    tmp = tempfile.mkdtemp(prefix="snaprec_")
    try:
        fps = max(0.05, count / max(0.2, duration))
        cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-i", path,
               "-vf", f"fps={fps:.4f}", "-frames:v", str(count), os.path.join(tmp, "f%02d.png")]
        subprocess.run(cmd, capture_output=True, timeout=120, **_popen_kwargs())
        images = []
        for name in sorted(os.listdir(tmp)):
            with Image.open(os.path.join(tmp, name)) as im:
                images.append(im.convert("RGB"))
        return images
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---- Filter-Kette --------------------------------------------------------

@dataclass
class Plan:
    video_filter: str
    size: tuple
    factor: float
    steps: list = field(default_factory=list)   # Beschreibung für die Oberfläche
    preset: str = "medium"
    crf: int = 17


def build_plan(width, height, resolution, analysis=None, filters=None):
    """Beste Filter-Kette für Größe, Ziel und erkannten Inhalt."""
    filters = available_filters() if filters is None else filters
    W, H = output_size(width, height, resolution)
    factor = upscale_factor(width, height, resolution)
    chain, steps = [], []
    if factor > 1.02:
        analysis = analysis or Analysis()
        strength = 0.8 if analysis.blurry else 0.6
        if analysis.content == "screen":
            if factor >= 1.8 and "xbr" in filters:
                # xBR vergrößert Kanten ohne Treppen; mehr als ×3 kostet nur Zeit
                n = 3 if factor >= 2.6 else 2
                chain.append(f"xbr={n}")
                steps.append(f"xBR ×{n} – Kanten-Vergrößerung für Text & Oberflächen")
        else:
            strength = 0.65 if analysis.blurry else 0.45
            if "hqdn3d" in filters:
                chain.append("hqdn3d=1.5:1.5:4:4")
                steps.append("Kompressions-Artefakte entfernen")
        chain.append(f"scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos")
        steps.append(f"Lanczos-Skalierung auf {W} × {H}")
        if "cas" in filters:
            chain.append(f"cas={strength:.2f}")
            steps.append("Kontrastadaptive Schärfung (CAS)" + (" – verstärkt, Quelle war weich" if analysis.blurry else ""))
        else:
            chain.append(f"unsharp=5:5:{strength + 0.3:.2f}:3:3:0.0")
            steps.append("Nachschärfen")
    elif (W, H) != (width // 2 * 2, height // 2 * 2):
        chain.append(f"scale={W}:{H}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos")
        steps.append(f"Verkleinern auf {W} × {H} (Lanczos)")
    else:
        chain.append(f"scale={W}:{H}")
    chain.append(f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black")
    chain.append("setsar=1")
    chain.append("format=yuv420p")
    pixels = W * H
    preset = "fast" if pixels <= 1920 * 1080 else "faster" if pixels <= 2560 * 1440 else "veryfast"
    return Plan(",".join(chain), (W, H), factor, steps, preset, 17 if pixels <= 2560 * 1440 else 18)


# ---- Verarbeitung --------------------------------------------------------

class Processor(threading.Thread):
    """Macht aus der Rohaufnahme das fertige Video.

    Für den Ladebildschirm: phase ("analyse" / "render" / "fallback" / "done"),
    progress (0..1), plan, analysis, eta (Sekunden oder None).
    """

    def __init__(self, raw_video, tracks, out_path, src_size, resolution, duration):
        super().__init__(daemon=True)
        self.raw_video = raw_video
        self.tracks = list(tracks)          # [(pfad, kanäle)]
        self.out_path = out_path
        self.src_size = src_size
        self.resolution = resolution
        self.duration = max(0.1, duration)
        self.phase = "analyse"
        self.progress = 0.0
        self.analysis = None
        self.plan = None
        self.eta = None
        self.error = None
        self.skipped_upscale = False
        self._cancel = threading.Event()
        self._proc = None

    def cancel(self):
        """Hochskalieren abbrechen – Video wird in Originalgröße gespeichert."""
        self._cancel.set()
        proc = self._proc
        if proc and proc.poll() is None:
            proc.kill()

    @property
    def cancelled(self):
        return self._cancel.is_set()

    def run(self):
        try:
            if not os.path.exists(self.raw_video) or os.path.getsize(self.raw_video) == 0:
                raise RuntimeError("Die Aufnahme war zu kurz – es wurde kein Bild aufgenommen.")
            w, h = self.src_size
            if upscale_factor(w, h, self.resolution) > 1.02:
                self.analysis = analyze_images(sample_frames(self.raw_video, self.duration))
            self.plan = build_plan(w, h, self.resolution, self.analysis)
            self.phase = "render"
            ok = self._encode(self.plan.video_filter, ["-c:v", "libx264", "-preset", self.plan.preset,
                                                      "-crf", str(self.plan.crf)])
            if not ok:
                if self.error and not self.cancelled:
                    raise self.error
                # Abgebrochen: schnell in Originalgröße speichern
                self.phase = "fallback"
                self.skipped_upscale = True
                self._cancel.clear()
                self.error = None
                ok = self._encode("format=yuv420p", ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"])
                if not ok and self.error:
                    raise self.error
            self.progress = 1.0
            self.phase = "done"
        except Exception as exc:
            self.error = exc
            self.phase = "done"
        finally:
            self._cleanup()

    def _encode(self, video_filter, codec_args):
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-nostats", "-progress", "pipe:1",
               "-i", self.raw_video]
        for path, channels in self.tracks:
            cmd += ["-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", str(channels), "-i", path]
        graph = f"[0:v]{video_filter}[v]"
        if len(self.tracks) == 1:
            graph += ";[1:a]apad[a]"
        elif self.tracks:
            inputs = "".join(f"[{i + 1}:a]" for i in range(len(self.tracks)))
            graph += f";{inputs}amix=inputs={len(self.tracks)}:duration=longest:normalize=0,apad[a]"
        cmd += ["-filter_complex", graph, "-map", "[v]"]
        if self.tracks:
            cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "320k", "-ar", str(SAMPLE_RATE), "-ac", "2"]
        cmd += codec_args + ["-t", f"{self.duration:.3f}", "-movflags", "+faststart", self.out_path]

        start = time.perf_counter()
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True, errors="replace", **_popen_kwargs())
        stderr_lines = []
        threading.Thread(target=lambda: stderr_lines.extend(self._proc.stderr), daemon=True).start()
        for line in self._proc.stdout:
            m = re.match(r"out_time_(?:us|ms)=(\d+)", line.strip())
            if m:
                done = int(m.group(1)) / 1e6
                self.progress = max(0.0, min(0.999, done / self.duration))
                elapsed = time.perf_counter() - start
                if self.progress > 0.03:
                    self.eta = elapsed / self.progress - elapsed
        code = self._proc.wait()
        if self.cancelled:
            return False
        if code != 0:
            self.error = RuntimeError("".join(stderr_lines).strip()[-600:] or f"ffmpeg-Fehler {code}")
            return False
        return True

    def _cleanup(self):
        if self.phase == "done" and self.error is None:
            paths = [self.raw_video] + [p for p, _ in self.tracks]
        else:
            paths = [p for p, _ in self.tracks]
            # Fehler: Rohvideo als Notlösung behalten
            if self.error is not None and os.path.exists(self.raw_video) and not os.path.exists(self.out_path):
                try:
                    os.replace(self.raw_video, self.out_path)
                except OSError:
                    pass
        for p in paths:
            try:
                os.remove(p)
            except OSError:
                pass
