"""Tonaufnahme: PC-Sound (was du hörst) und Mikrofon.

Jede Quelle läuft in einem eigenen Thread und schreibt die Samples verlustfrei
(32-Bit-Gleitkomma, 48 kHz) in eine Datei. Die Position im Ton richtet sich nach der Uhr der
Videoaufnahme – so bleiben Bild und Ton synchron, auch bei Pausen oder wenn
eine Quelle kurz keine Daten liefert (Lücken werden mit Stille gefüllt).
Am Ende mischt ffmpeg alles zusammen ins MP4 (AAC, 320 kbit/s, Stereo).
"""

import subprocess
import sys
import threading
import time
import warnings

import imageio_ffmpeg

SAMPLE_RATE = 48000
BLOCK = 1024
IS_WINDOWS = sys.platform == "win32"

SOURCE_NAMES = {"system": "PC-Sound", "mic": "Mikrofon"}


class AudioError(RuntimeError):
    pass


def _soundcard():
    try:
        warnings.filterwarnings("ignore", message=".*discontinuity.*")
        import soundcard
        return soundcard
    except Exception as exc:
        raise AudioError(f"Tonaufnahme hier nicht verfügbar ({exc})") from exc


def get_source(kind):
    """Standard-Gerät für 'system' (Loopback der Lautsprecher) oder 'mic'."""
    sc = _soundcard()
    try:
        if kind == "system":
            speaker = sc.default_speaker()
            if speaker is None:
                raise AudioError("Kein Lautsprecher gefunden")
            return sc.get_microphone(id=str(speaker.name), include_loopback=True)
        mic = sc.default_microphone()
        if mic is None:
            raise AudioError("Kein Mikrofon gefunden")
        return mic
    except AudioError:
        raise
    except Exception as exc:
        name = SOURCE_NAMES.get(kind, kind)
        raise AudioError(f"{name} nicht gefunden ({exc})") from exc


class AudioTrack(threading.Thread):
    """Nimmt eine Quelle auf. clock(now) liefert die aktive Videozeit in
    Sekunden (None = Video läuft noch nicht), paused() ob pausiert ist."""

    def __init__(self, kind, source, path, clock, paused):
        super().__init__(daemon=True)
        self.kind = kind
        self.source = source
        self.path = path
        self.clock = clock
        self.paused = paused
        self.channels = max(1, min(2, int(getattr(source, "channels", 2) or 2)))
        self.ready = threading.Event()
        self._stop_event = threading.Event()
        self.error = None
        self.frames = 0

    @property
    def name(self):
        return SOURCE_NAMES.get(self.kind, self.kind)

    def stop(self):
        self._stop_event.set()

    def run(self):
        import numpy as np
        if IS_WINDOWS:
            try:  # COM für diesen Thread (WASAPI)
                import ctypes
                ctypes.windll.ole32.CoInitializeEx(None, 0)
            except Exception:
                pass
        tolerance = int(0.08 * SAMPLE_RATE)
        bytes_per_frame = 4 * self.channels
        try:
            with self.source.recorder(samplerate=SAMPLE_RATE, channels=self.channels,
                                      blocksize=BLOCK) as rec, open(self.path, "wb") as out:
                self.ready.set()
                written = 0
                while not self._stop_event.is_set():
                    data = rec.record(numframes=BLOCK)
                    now = time.perf_counter()
                    if self.paused():
                        continue
                    active = self.clock(now)
                    if active is None:
                        continue
                    data = np.asarray(data, dtype=np.float32).reshape(-1, self.channels)
                    n = len(data)
                    start = int(active * SAMPLE_RATE) - n
                    if start < 0:                      # Teil vor Videostart verwerfen
                        data = data[min(n, -start):]
                        start = 0
                    if start > written + tolerance:    # Lücke -> Stille einfügen
                        gap = start - written
                        out.write(b"\x00" * (gap * bytes_per_frame))
                        written += gap
                    if len(data):
                        out.write(np.ascontiguousarray(data, dtype="<f4").tobytes())
                        written += len(data)
                        out.flush()
                    self.frames = written
        except Exception as exc:
            self.error = exc
        finally:
            self.ready.set()


def _popen_kwargs():
    if IS_WINDOWS:
        return {"creationflags": 0x08000000}  # CREATE_NO_WINDOW – kein schwarzes Fenster
    return {}


def mux(video_path, tracks, out_path, duration):
    """Video + Tonspuren (Liste von (pfad, kanäle)) zu einem MP4 zusammenfügen."""
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", video_path]
    for path, channels in tracks:
        cmd += ["-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", str(channels), "-i", path]
    if len(tracks) == 1:
        graph = "[1:a]apad[a]"
    else:
        inputs = "".join(f"[{i + 1}:a]" for i in range(len(tracks)))
        graph = f"{inputs}amix=inputs={len(tracks)}:duration=longest:normalize=0,apad[a]"
    cmd += ["-filter_complex", graph, "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "320k", "-ar", str(SAMPLE_RATE), "-ac", "2",
            "-t", f"{max(duration, 0.1):.3f}", "-movflags", "+faststart", out_path]
    result = subprocess.run(cmd, capture_output=True, text=True, **_popen_kwargs())
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg-Fehler beim Zusammenfügen")
