"""Die eigentliche Aufnahme – läuft in einem eigenen Thread."""

import os
import threading
import time

import imageio_ffmpeg
from PIL import Image, ImageDraw

from snaprec import audio
from snaprec.utils import MSS

CURSOR_SHAPE = [(0, 0), (0, 17), (4, 13), (7, 20), (10, 19), (7, 12), (12, 12)]

# Ausgabe-Auflösungen: "1080p" = 1920×1080 (quer) bzw. 1080×1920 (hochkant)
RESOLUTIONS = ("1080p", "original")


def draw_cursor(img, x, y):
    if not (-20 <= x < img.width and -20 <= y < img.height):
        return
    pts = [(x + px, y + py) for px, py in CURSOR_SHAPE]
    ImageDraw.Draw(img).polygon(pts, fill="white", outline="black")


def output_size(region, resolution):
    """Größe des fertigen Videos. Hochkant-Bereiche werden zu 1080×1920."""
    if resolution != "1080p":
        return region["width"], region["height"]
    return (1920, 1080) if region["width"] >= region["height"] else (1080, 1920)


def upscale_factor(region, resolution):
    """> 1, wenn der Bereich kleiner ist als das Video und hochskaliert wird."""
    w, h = output_size(region, resolution)
    return min(w / max(1, region["width"]), h / max(1, region["height"]))


def video_filter(region, resolution):
    """ffmpeg-Filter: Bereich auf 1080p skalieren (bei abweichendem
    Seitenverhältnis mit schwarzen Rändern), beim Vergrößern leicht nachschärfen."""
    w, h = output_size(region, resolution)
    if (w, h) == (region["width"], region["height"]):
        return None
    sharpen = ",unsharp=5:5:0.5:3:3:0.0" if upscale_factor(region, resolution) > 1.1 else ""
    same_ratio = abs(region["width"] / region["height"] - w / h) / (w / h) < 0.01
    if same_ratio:
        return f"scale={w}:{h}:flags=lanczos{sharpen},setsar=1"
    return (f"scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2"
            f":flags=lanczos{sharpen},pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")


class Recorder(threading.Thread):
    """Nimmt den Bereich mit fester Bildrate auf und schreibt ein MP4 (H.264),
    auf Wunsch mit Ton (audio_sources: "system" und/oder "mic").

    Ist der Rechner mal zu langsam, werden Bilder doppelt geschrieben, damit
    das Video trotzdem genauso lang ist wie die echte Aufnahme.
    """

    def __init__(self, region, fps, path, cursor_pos=None, resolution="1080p",
                 audio_sources=(), source_factory=None):
        super().__init__(daemon=True)
        self.region = region
        self.fps = fps
        self.path = path
        self.cursor_pos = cursor_pos  # Callable -> (x, y) oder None
        self.resolution = resolution
        self.size = output_size(region, resolution)
        self.audio_sources = list(audio_sources)
        self.source_factory = source_factory or audio.get_source
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._t0 = None
        self._paused_total = 0.0
        self._pause_began = None
        self.error = None
        self.warnings = []
        self.audio_names = []     # Quellen, die wirklich im Video gelandet sind
        self.frames = 0
        self.elapsed = 0.0

    # ---- gemeinsame Uhr für Bild und Ton ------------------------------------
    def active_time(self, now=None):
        """Aufgenommene Zeit in Sekunden (ohne Pausen) oder None vor dem Start."""
        now = time.perf_counter() if now is None else now
        with self._lock:
            if self._t0 is None:
                return None
            paused = self._paused_total
            if self._pause_began is not None:
                paused += now - self._pause_began
            return max(0.0, now - self._t0 - paused)

    def stop(self):
        self._stop_event.set()

    def set_paused(self, paused):
        now = time.perf_counter()
        with self._lock:
            if paused and self._pause_began is None:
                self._pause_began = now
            elif not paused and self._pause_began is not None:
                self._paused_total += now - self._pause_began
                self._pause_began = None

    @property
    def paused(self):
        return self._pause_began is not None

    def run(self):
        try:
            self._record()
        except Exception as exc:  # Fehler an die Oberfläche weiterreichen
            self.error = exc

    # ---- Ablauf ------------------------------------------------------------
    def _start_audio(self, base):
        tracks = []
        for kind in self.audio_sources:
            try:
                source = self.source_factory(kind)
                track = audio.AudioTrack(kind, source, f"{base}_{kind}.pcm",
                                         self.active_time, lambda: self.paused)
                track.start()
                tracks.append(track)
            except Exception as exc:
                self.warnings.append(f"{audio.SOURCE_NAMES.get(kind, kind)}: {exc}")
        for track in tracks:
            track.ready.wait(5)
        ok = []
        for track in tracks:
            if track.error:
                self.warnings.append(f"{track.name}: {track.error}")
            else:
                ok.append(track)
        return ok

    def _record(self):
        folder, name = os.path.split(self.path)
        base = os.path.join(folder, "." + os.path.splitext(name)[0])
        tracks = self._start_audio(base) if self.audio_sources else []
        video_path = f"{base}_video.mp4" if tracks else self.path
        try:
            self._record_video(video_path)
        finally:
            for track in tracks:
                track.stop()
            for track in tracks:
                track.join(timeout=3)
        if not tracks:
            return
        try:
            usable = []
            for track in tracks:
                if track.error:
                    self.warnings.append(f"{track.name}: {track.error}")
                elif os.path.exists(track.path) and os.path.getsize(track.path) > 0:
                    usable.append(track)
            if usable:
                audio.mux(video_path, [(t.path, t.channels) for t in usable], self.path,
                          self.frames / self.fps)
                self.audio_names = [t.name for t in usable]
                os.remove(video_path)
            else:
                os.replace(video_path, self.path)
        except Exception as exc:
            self.warnings.append(f"Ton konnte nicht eingefügt werden: {exc}")
            if os.path.exists(video_path):
                os.replace(video_path, self.path)
        finally:
            for track in tracks:
                try:
                    os.remove(track.path)
                except OSError:
                    pass

    def _record_video(self, path):
        r = self.region
        params = ["-crf", "18", "-preset", "veryfast", "-movflags", "+faststart"]
        vf = video_filter(r, self.resolution)
        if vf:
            params = ["-vf", vf] + params
        writer = imageio_ffmpeg.write_frames(
            path, (r["width"], r["height"]), fps=self.fps, codec="libx264",
            quality=None, macro_block_size=2, pix_fmt_in="rgb24", pix_fmt_out="yuv420p",
            output_params=params,
        )
        writer.send(None)
        interval = 1.0 / self.fps
        try:
            with MSS() as sct:
                with self._lock:
                    self._t0 = time.perf_counter()
                while not self._stop_event.is_set():
                    if self.paused:
                        self._stop_event.wait(0.02)
                        continue
                    shot = sct.grab(r)
                    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                    if self.cursor_pos:
                        pos = self.cursor_pos()
                        if pos:
                            draw_cursor(img, pos[0] - r["left"], pos[1] - r["top"])
                    data = img.tobytes()

                    self.elapsed = self.active_time()
                    target = int(self.elapsed * self.fps) + 1
                    while self.frames < target:
                        writer.send(data)
                        self.frames += 1

                    delay = (self.frames * interval - self.active_time())
                    if delay > 0:
                        self._stop_event.wait(delay)
                self.elapsed = self.active_time()
        finally:
            writer.close()
