"""Schreibt die Windows-Versionsinfos (Herausgeber, Version …) für PyInstaller.

    python tools/version_info.py build/version_info.txt
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from snaprec import APP_NAME, PUBLISHER, VERSION  # noqa: E402

TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={v4}, prodvers={v4}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040704B0', [
      StringStruct('CompanyName', '{pub}'),
      StringStruct('FileDescription', '{app} – Bildschirmbereich aufnehmen'),
      StringStruct('FileVersion', '{ver}'),
      StringStruct('InternalName', '{app}'),
      StringStruct('LegalCopyright', '© {pub} · MIT-Lizenz'),
      StringStruct('OriginalFilename', '{app}.exe'),
      StringStruct('ProductName', '{app}'),
      StringStruct('ProductVersion', '{ver}')])]),
    VarFileInfo([VarStruct('Translation', [0x0407, 1200])])
  ]
)
"""


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "build" / "version_info.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    parts = [int(x) for x in VERSION.split(".")] + [0, 0, 0]
    v4 = tuple(parts[:4])
    out.write_text(TEMPLATE.format(v4=v4, ver=VERSION, app=APP_NAME, pub=PUBLISHER), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
