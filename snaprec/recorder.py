"""Die eigentliche Aufnahme – läuft in einem eigenen Thread."""

import threading
import time

import imageio_ffmpeg
from PIL import Image, ImageDraw

from snaprec.utils import MSS

CURSOR_SHAPE = [(0, 0), (0, 17), (4, 13), (7, 20), (10, 19), (7, 12), (12, 12)]


def draw_cursor(img, x, y):
    if not (-20 <= x < img.width and -20 <= y < img.height):
        return
    pts = [(x + px, y + py) for px, py in CURSOR_SHAPE]
    ImageDraw.Draw(img).polygon(pts, fill="white", outline="black")


class Recorder(threading.Thread):
    """Nimmt den Bereich mit fester Bildrate auf und schreibt ein MP4 (H.264).

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
        writer = imageio_ffmpeg.write_frames(
            self.path, (r["width"], r["height"]), fps=self.fps, codec="libx264",
            quality=None, macro_block_size=2, pix_fmt_in="rgb24", pix_fmt_out="yuv420p",
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

                    delay = start + paused_total + self.frames * interval - time.perf_counter()
                    if delay > 0:
                        self._stop_event.wait(delay)
        finally:
            writer.close()
