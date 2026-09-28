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
    rec = Recorder(region, 20, path, cursor_pos=lambda: (10, 10))
    rec.start()
    time.sleep(1.0)
    rec.set_paused(True)
    time.sleep(0.5)          # Pause darf das Video nicht verlängern
    rec.set_paused(False)
    time.sleep(0.5)
    rec.stop()
    rec.join(timeout=20)
    assert rec.error is None
    assert os.path.getsize(path) > 0

    info = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-i", path],
                          capture_output=True, text=True).stderr
    assert "h264" in info and "200x150" in info
    frames, _ = imageio_ffmpeg.count_frames_and_secs(path)
    assert 25 <= frames <= 40   # ~1,5 s bei 20 fps


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
