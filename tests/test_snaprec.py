"""Tests für SnapRec. Die Aufnahme-Tests brauchen einen Bildschirm
(unter Linux z. B. mit:  xvfb-run python -m pytest tests)."""

import os
import subprocess
import sys
import time
from pathlib import Path

import imageio_ffmpeg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from snaprec import hotkeys, intro, theme, utils  # noqa: E402
from snaprec.recorder import Recorder  # noqa: E402


def _has_display():
    if sys.platform in ("win32", "darwin"):
        return True
    return bool(os.environ.get("DISPLAY"))


needs_display = pytest.mark.skipif(not _has_display(), reason="kein Bildschirm verfügbar")


# ---- Hilfsfunktionen -------------------------------------------------------

def test_normalize_region_sorts_and_makes_even():
    r = utils.normalize_region(421, 341, 100, 100)
    assert r == {"left": 100, "top": 100, "width": 320, "height": 240}


def test_format_helpers():
    assert utils.format_time(0) == "00:00"
    assert utils.format_time(75.9) == "01:15"
    assert utils.format_size(3_500_000) == "3,3 MB"


def test_config_roundtrip(tmp_path):
    path = tmp_path / "cfg.json"
    cfg = utils.default_config()
    cfg["countdown"] = 5
    cfg["hotkeys"]["toggle"] = "win+shift+f9"
    utils.save_config(cfg, path)
    loaded = utils.load_config(path)
    assert loaded["countdown"] == 5
    assert loaded["hotkeys"]["toggle"] == "win+shift+f9"
    assert loaded["hotkeys"]["pause"] == utils.DEFAULT_HOTKEYS["pause"]


# ---- Tastenkürzel ----------------------------------------------------------

@pytest.mark.parametrize("combo, expected", [
    ("Alt+Ctrl+R", "ctrl+alt+r"),
    ("shift+win+f9", "shift+win+f9"),
    ("f5", "f5"),
    ("print_screen", "print_screen"),
    ("ctrl+alt+page_down", "ctrl+alt+page_down"),
])
def test_hotkey_normalize(combo, expected):
    assert hotkeys.normalize(combo) == expected


@pytest.mark.parametrize("combo", ["r", "shift+r", "ctrl+alt", "ctrl+ä", "ctrl+r+t", ""])
def test_hotkey_invalid(combo):
    with pytest.raises(hotkeys.HotkeyError):
        hotkeys.parse(combo)


def test_hotkey_labels_and_backends():
    assert hotkeys.label("ctrl+alt+r") == "Strg + Alt + R"
    assert hotkeys.label_parts("win+shift+page_up") == ["Shift", "Win", "Bild ↑"]
    assert hotkeys.to_pynput("ctrl+win+f2") == "<ctrl>+<cmd>+<f2>"
    assert hotkeys.to_windows("ctrl+alt+r") == (0x3, ord("R"))
    assert hotkeys.to_windows("shift+win+f1") == (0xC, 0x70)


def test_hotkey_from_tk_event():
    assert hotkeys.key_from_tk_event("Control_L", 17) is None
    assert hotkeys.key_from_tk_event("F9", 0) == "f9"
    assert hotkeys.key_from_tk_event("Next", 0) == "page_down"
    assert hotkeys.modifiers_from_tk_state(0x5) == {"ctrl", "shift"}


# ---- Grafik ----------------------------------------------------------------

def test_theme_images():
    assert theme.logo_image(64).size == (64, 64)
    assert theme.countdown_badge(120, 3, 0.4).size == (120, 120)
    assert theme.keycaps(["Strg", "Alt", "R"], 24).height == 24
    for name in ("record", "stop", "pause", "play", "gear", "help", "check_circle", "keyboard"):
        assert theme.icon_image(name, 32).size == (32, 32)


def test_intro_scenes_render():
    for i, (_, _, dur) in enumerate(intro.SCENES):
        for t in (0, dur / 2, dur):
            img = intro.render_scene(i, t, 1.0)
            assert img.size == (intro.W, intro.H)


# ---- Aufnahme --------------------------------------------------------------

@needs_display
def test_recorder_writes_playable_mp4(tmp_path):
    path = str(tmp_path / "test.mp4")
    region = utils.normalize_region(0, 0, 200, 150)
    rec = Recorder(region, 20, path, cursor_pos=lambda: (10, 10), resolution="original")
    rec.start()
    time.sleep(1.0)
    rec.set_paused(True)
    time.sleep(0.5)          # Pause darf das Video nicht verlängern
    rec.set_paused(False)
    time.sleep(0.5)
    rec.stop()
    rec.join(timeout=20)
    assert rec.error is None
    rec.process()
    assert os.path.getsize(path) > 0

    info = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", path],
                          capture_output=True, text=True).stderr
    assert "h264" in info and "200x150" in info
    frames, _ = imageio_ffmpeg.count_frames_and_secs(path)
    assert frames == rec.frames          # beim Verarbeiten geht kein Bild verloren
    # 1,5 s aktiv bei 20 fps (Pause zählt nicht); etwas Spielraum für den
    # Start des Kodierers auf langsamen Rechnern
    assert 15 <= rec.frames <= 34


@pytest.mark.skipif(sys.platform != "win32", reason="nur Windows")
def test_windows_global_hotkey_fires():
    """Registriert ein Kürzel und simuliert den Tastendruck."""
    import ctypes
    manager = hotkeys.HotkeyManager()
    errors = manager.apply({"toggle": "ctrl+alt+shift+f11"})
    assert errors == {}
    user32 = ctypes.windll.user32
    keys = [0x11, 0x12, 0x10, 0x7A]            # Strg, Alt, Shift, F11
    for vk in keys:
        user32.keybd_event(vk, 0, 0, 0)
    for vk in reversed(keys):
        user32.keybd_event(vk, 0, 2, 0)       # KEYEVENTF_KEYUP
    fired = []
    for _ in range(40):
        fired += manager.poll()
        if fired:
            break
        time.sleep(0.05)
    manager.stop()
    assert fired == ["toggle"]


# ---- 1080p, Ton, Löschen ---------------------------------------------------

class FakeSource:
    """Tut so, als wäre es ein Mikrofon: liefert in Echtzeit einen 440-Hz-Ton."""
    channels = 2

    def recorder(self, samplerate, channels, blocksize):
        import numpy as np
        src = self

        class Rec:
            def __enter__(self):
                self.pos = 0
                return self

            def __exit__(self, *a):
                return False

            def record(self, numframes):
                time.sleep(numframes / samplerate)
                t = (np.arange(numframes) + self.pos) / samplerate
                self.pos += numframes
                wave = 0.5 * np.sin(2 * np.pi * 440 * t)
                return np.repeat(wave[:, None], src.channels, axis=1).astype("float32")
        return Rec()


def _streams(path):
    return subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
                          capture_output=True, text=True).stderr


def test_output_sizes_for_all_qualities():
    from snaprec import processing as pr
    assert pr.output_size(800, 600, "1080p") == (1920, 1080)
    assert pr.output_size(800, 600, "1440p") == (2560, 1440)
    assert pr.output_size(800, 600, "4k") == (3840, 2160)
    assert pr.output_size(562, 1000, "4k") == (2160, 3840)     # hochkant
    assert pr.output_size(801, 601, "original") == (800, 600)
    assert pr.upscale_factor(1280, 720, "1080p") == 1.5
    assert pr.upscale_factor(3840, 2160, "1080p") == 0.5


@needs_display
def test_recording_1080p_with_audio(tmp_path):
    path = tmp_path / "ton.mp4"
    rec = Recorder(utils.normalize_region(0, 0, 320, 240), 20, str(path), resolution="1080p",
                   audio_sources=["mic"], source_factory=lambda kind: FakeSource())
    rec.start()
    time.sleep(1.2)
    rec.stop()
    rec.join(timeout=30)
    assert rec.error is None and rec.warnings == []
    rec.process()
    assert rec.audio_names == ["Mikrofon"]
    info = _streams(path)
    assert "1920x1080" in info
    assert "Audio: aac" in info and "48000 Hz" in info and "stereo" in info
    # keine Zwischendateien übrig
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ton.mp4"]


@needs_display
def test_missing_audio_device_still_saves_video(tmp_path):
    from snaprec.audio import AudioError

    def no_device(kind):
        raise AudioError("Kein Mikrofon gefunden")
    path = tmp_path / "ohne.mp4"
    rec = Recorder(utils.normalize_region(0, 0, 200, 150), 20, str(path), resolution="original",
                   audio_sources=["mic"], source_factory=no_device)
    rec.start()
    time.sleep(0.6)
    rec.stop()
    rec.join(timeout=30)
    assert rec.error is None
    rec.process()
    assert rec.warnings and "Kein Mikrofon" in rec.warnings[0]
    info = _streams(path)
    assert "200x150" in info and "Audio" not in info


def test_audio_mux_mixes_two_tracks(tmp_path):
    import numpy as np
    from snaprec import audio
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    video = tmp_path / "v.mp4"
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=black:s=64x48:d=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
    tracks = []
    for i, ch in enumerate((2, 1)):
        p = tmp_path / f"a{i}.pcm"
        t = np.arange(audio.SAMPLE_RATE) / audio.SAMPLE_RATE
        data = (0.3 * np.sin(2 * np.pi * (440 + 220 * i) * t)).astype("<f4")
        p.write_bytes(np.repeat(data[:, None], ch, axis=1).tobytes())
        tracks.append((str(p), ch))
    out = tmp_path / "out.mp4"
    audio.mux(str(video), tracks, str(out), 1.0)
    info = _streams(out)
    assert "Audio: aac" in info and "stereo" in info


def test_library_list_and_delete(tmp_path, monkeypatch):
    from snaprec import library
    for i, name in enumerate(["a.mp4", "b.MP4", "notiz.txt", ".versteckt.mp4"]):
        (tmp_path / name).write_bytes(b"x")
        os.utime(tmp_path / name, (1000 + i, 1000 + i))
    names = [p.name for p in library.list_recordings(tmp_path)]
    assert names == ["b.MP4", "a.mp4"]
    trashed = []
    import send2trash
    monkeypatch.setattr(send2trash, "send2trash", lambda p: (trashed.append(p), os.remove(p)))
    assert library.delete_recording(tmp_path / "a.mp4") is True
    assert not (tmp_path / "a.mp4").exists() and trashed


def test_portrait_region_becomes_vertical_1080p():
    """Fehler aus der Praxis: ein hoher, schmaler Bereich (z. B. ein Handy-Video)
    landete mit riesigen schwarzen Rändern in einem 1920×1080-Video."""
    from snaprec import recorder
    portrait = utils.normalize_region(0, 0, 562, 1000)
    assert recorder.output_size(portrait, "1080p") == (1080, 1920)
    assert recorder.upscale_factor(portrait, "1080p") > 1.9


def test_selection_snaps_to_16_9_and_9_16():
    from types import SimpleNamespace
    from snaprec.overlay import SelectionOverlay
    ov = SimpleNamespace(lock_ratio=True, _start=(100, 100), screen={"width": 1920, "height": 1080})
    snap = SelectionOverlay._constrain
    assert snap(ov, 900, 300) == (900, 550)          # quer: 800 breit -> 450 hoch
    assert snap(ov, 400, 900) == (550, 900)          # hochkant: 800 hoch -> 450 breit
    assert snap(ov, 400, 900, state=0x1) == (400, 900)   # Shift = frei
    x2, y2 = snap(ov, 1900, 1050)                    # am Bildschirmrand begrenzt
    assert x2 <= 1920 and y2 <= 1080 and abs((x2 - 100) / (y2 - 100) - 16 / 9) < 0.01
    ov.lock_ratio = False
    assert snap(ov, 400, 900) == (400, 900)


@needs_display
def test_portrait_recording_is_1080x1920(tmp_path):
    path = tmp_path / "hoch.mp4"
    rec = Recorder(utils.normalize_region(0, 0, 562, 1000), 20, str(path), resolution="1080p")
    rec.start()
    time.sleep(0.6)
    rec.stop()
    rec.join(timeout=30)
    assert rec.error is None
    proc = rec.process()
    assert "1080x1920" in _streams(path)
    assert proc.analysis is not None and proc.plan.factor > 1


# ---- Smarte Analyse & Hochskalieren ----------------------------------------

def _ui_image():
    """Künstlicher Bildschirm-Inhalt: einfarbige Flächen, Text-Balken."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (640, 360), (238, 241, 247))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 640, 40), fill=(40, 44, 52))
    for i in range(8):
        d.rectangle((30, 70 + i * 32, 30 + 60 * (i % 5 + 3), 82 + i * 32), fill=(60, 66, 80))
    d.rectangle((420, 90, 600, 300), fill=(124, 92, 255))
    return img


def _photo_image(seed=1):
    """Künstlicher Foto-Inhalt: weiche Verläufe und Rauschen."""
    import random
    from PIL import Image, ImageFilter
    rnd = random.Random(seed)
    grad = Image.linear_gradient("L").resize((640, 360))
    chans = [Image.blend(Image.effect_noise((640, 360), 40 + 10 * i), grad.rotate(90 * i, expand=False), 0.6)
             for i in range(3)]
    img = Image.merge("RGB", chans).filter(ImageFilter.GaussianBlur(1))
    return img.rotate(rnd.randint(0, 5))


def test_analysis_detects_screen_and_video_content():
    from snaprec import processing as pr
    screen = pr.analyze_images([_ui_image() for _ in range(3)])
    assert screen.content == "screen"
    video = pr.analyze_images([_photo_image(i) for i in range(3)])
    assert video.content == "video"
    assert video.motion >= 0 and screen.frames == 3


def test_plan_picks_method_by_content():
    from snaprec import processing as pr
    filters = frozenset({"xbr", "cas", "hqdn3d"})
    screen = pr.Analysis(content="screen", sharpness=500)
    plan = pr.build_plan(562, 1000, "1440p", screen, filters)
    assert plan.size == (1440, 2560) and plan.video_filter.startswith("xbr=2,")
    assert "cas=" in plan.video_filter and "lanczos" in plan.video_filter
    video = pr.Analysis(content="video", sharpness=50)            # weich -> stärker schärfen
    plan = pr.build_plan(1280, 720, "4k", video, filters)
    assert plan.video_filter.startswith("hqdn3d") and "xbr" not in plan.video_filter
    assert "cas=0.65" in plan.video_filter and plan.preset == "veryfast"
    down = pr.build_plan(3840, 2160, "1080p", None, filters)       # verkleinern: kein Schärfen
    assert "cas" not in down.video_filter and down.factor < 1
    old = pr.build_plan(562, 1000, "1080p", screen, frozenset())   # ffmpeg ohne cas/xbr
    assert "unsharp" in old.video_filter and "xbr" not in old.video_filter


def test_processor_cancel_saves_original_size(tmp_path):
    """„Überspringen“ im Ladebildschirm: Video trotzdem speichern, in Originalgröße."""
    from snaprec import processing as pr
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    raw = tmp_path / ".roh.mp4"
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=320x240:d=3:r=30",
                    "-c:v", "libx264", "-pix_fmt", "yuv444p", str(raw)], check=True)
    out = tmp_path / "fertig.mp4"
    proc = pr.Processor(str(raw), [], str(out), (320, 240), "4k", 3.0)
    proc.start()
    while proc.phase == "analyse":
        time.sleep(0.01)
    proc.cancel()
    proc.join(timeout=60)
    assert proc.error is None and proc.skipped_upscale
    assert "320x240" in _streams(out) and not raw.exists()


def test_processor_reports_progress_and_cleans_up(tmp_path):
    from snaprec import processing as pr
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    raw = tmp_path / ".roh.mp4"
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=640x360:d=2:r=30",
                    "-c:v", "libx264", "-pix_fmt", "yuv444p", str(raw)], check=True)
    out = tmp_path / "fertig.mp4"
    proc = pr.Processor(str(raw), [], str(out), (640, 360), "1080p", 2.0)
    seen = []
    proc.start()
    while proc.is_alive():
        seen.append(proc.progress)
        time.sleep(0.02)
    assert proc.error is None and proc.progress == 1.0 and proc.analysis is not None
    assert "1920x1080" in _streams(out) and "yuv420p" in _streams(out)
    assert not raw.exists()


def test_empty_recording_gives_clear_error(tmp_path):
    from snaprec import processing as pr
    raw = tmp_path / ".roh.mp4"
    raw.write_bytes(b"")
    proc = pr.Processor(str(raw), [], str(tmp_path / "x.mp4"), (100, 100), "1080p", 1.0)
    proc.run()
    assert proc.error is not None and "zu kurz" in str(proc.error)
