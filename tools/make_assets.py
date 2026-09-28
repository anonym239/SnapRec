"""Erzeugt Logo, Programm-Symbol und das Einführungs-GIF.

    python tools/make_assets.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from snaprec import intro, theme  # noqa: E402


def main():
    (ROOT / "assets").mkdir(exist_ok=True)
    (ROOT / "docs").mkdir(exist_ok=True)
    theme.logo_image(256).save(ROOT / "assets" / "icon.ico",
                               sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    theme.logo_image(256).save(ROOT / "assets" / "logo.png")
    if "--no-gif" not in sys.argv:
        n = intro.export_gif(str(ROOT / "docs" / "intro.gif"), k=1.2, fps=20)
        print(f"docs/intro.gif: {n} Bilder")


if __name__ == "__main__":
    main()
