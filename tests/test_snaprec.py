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
import snaprec  # noqa: E402


def test_normalize_region_sorts_and_makes_even():
    r = snaprec.normalize_region(421, 341, 100, 100)
    assert r == {"left": 100, "top": 100, "width": 320, "height": 240}


def test_format_time():
    assert snaprec.format_time(0) == "00:00"
    assert snaprec.format_time(75.9) == "01:15"


def _has_display():
    if sys.platform in ("win32", "darwin"):
        return True
    return bool(os.environ.get("DISPLAY"))


@pytest.mark.skipif(not _has_display(), reason="kein Bildschirm verfügbar")
def test_recorder_writes_playable_mp4(tmp_path):
    path = str(tmp_path / "test.mp4")
    region = snaprec.normalize_region(0, 0, 200, 150)
    rec = snaprec.Recorder(region, 20, path, cursor_pos=lambda: (10, 10))
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
