# SnapRec – Bildschirmbereich aufnehmen

Kostenloses Open-Source-Tool (MIT-Lizenz), das wie die **Bildschirmaufnahme im
Snipping Tool von Windows 11** funktioniert:

1. Auf **„＋ Neue Aufnahme“** klicken (oder `Strg+N`).
2. Der Bildschirm wird **grau abgedunkelt** – mit der Maus den Bereich aufziehen,
   der aufgenommen werden soll. Die Größe wird live angezeigt.
3. Ein **Countdown** (einstellbar: kein / 3 / 5 / 10 Sekunden) zählt herunter.
4. Die Aufnahme läuft – der Bereich ist **rot umrandet**, darunter sitzt eine
   kleine Leiste mit Zeit, **Pause** und **Stopp**.
5. Das Video wird als **MP4 (H.264)** gespeichert, standardmäßig in
   `Videos\SnapRec`. Danach direkt „Abspielen“ oder „Ordner öffnen“.

| Bereich auswählen | Countdown | Aufnahme läuft |
|---|---|---|
| ![Auswahl](docs/auswahl.png) | ![Countdown](docs/countdown.png) | ![Aufnahme](docs/aufnahme.png) |

## Bedienung

| Aktion | Taste / Maus |
|---|---|
| Neue Aufnahme | Button oder `Strg+N` |
| Bereich wählen | linke Maustaste ziehen |
| Ganzen Monitor aufnehmen | Doppelklick oder `Enter` im grauen Bildschirm |
| Auswahl abbrechen | `Esc` oder rechte Maustaste |
| Countdown abbrechen / überspringen | `Esc` / Klick auf die Zahl |
| Pause / Weiter, Stopp | Buttons in der Leiste (Leiste lässt sich verschieben) |
| Speicherort ändern | 📁-Button |

Weitere Einstellungen: Bilder pro Sekunde (15/24/30/60) und ob der Mauszeiger
mit aufgenommen wird. Alles wird in `~/.snaprec.json` gemerkt.

Mehrere Monitore werden unterstützt. Unter Windows 10 (ab 2004) / 11 werden
Rahmen und Steuerleiste automatisch aus dem Video ausgeblendet – selbst wenn du
den ganzen Bildschirm aufnimmst.

## Installation

### Windows – fertige .exe (ohne Python)
Auf GitHub unter **Actions → „SnapRec – testen & Windows-Programm bauen“** den
neuesten Lauf öffnen und unten bei *Artifacts* **SnapRec-Windows** herunterladen.
Entpacken, `SnapRec.exe` starten, fertig.

### Windows – mit Python
[Python 3.9+](https://www.python.org/downloads/) installieren, dann einfach
**`start_windows.bat`** doppelklicken. Beim ersten Start werden die Pakete
automatisch installiert.

### Linux / macOS
```sh
./start.sh
```
Unter Linux wird Tkinter benötigt (`sudo apt install python3-tk`) und eine
X11-Sitzung (unter Wayland bitte „GNOME auf Xorg“ o. Ä. wählen). Unter macOS
muss dem Terminal die Berechtigung „Bildschirmaufnahme“ erteilt werden.

### Manuell
```sh
pip install -r requirements.txt
python snaprec.py
```

## Kommandozeile

```text
python snaprec.py [-c SEKUNDEN] [--fps FPS] [-o ORDNER] [--no-cursor] [-s]

  -c, --countdown   Countdown in Sekunden (0 = keiner), z. B. -c 3
  --fps             Bilder pro Sekunde (Standard 30)
  -o, --output      Ordner für die Videos
  --no-cursor       Mauszeiger nicht aufnehmen
  -s, --start       sofort mit der Bereichsauswahl beginnen
```

Tipp: Eine Verknüpfung mit `SnapRec.exe -s -c 3` auf eine Tastenkombination
legen – dann startet die Auswahl direkt per Hotkey.

## Selbst bauen (.exe)
```sh
pip install -r requirements.txt pyinstaller
pyinstaller --onefile --windowed --name SnapRec --collect-all imageio_ffmpeg snaprec.py
```

## Tests
```sh
pip install pytest
python -m pytest tests          # unter Linux ohne Monitor: xvfb-run python -m pytest tests
```

## Technik
- **Tkinter** für Oberfläche, graues Overlay, Countdown und Steuerleiste
- **mss** für schnelle Bildschirmaufnahmen
- **imageio-ffmpeg** (bringt ffmpeg mit) für MP4/H.264
- Ist der Rechner kurz zu langsam, werden Bilder doppelt geschrieben – das Video
  ist deshalb immer genauso lang wie die echte Aufnahme.

Aktuell wird nur Bild aufgenommen, kein Ton.

## Lizenz
MIT – siehe [LICENSE](LICENSE). Mitmachen ausdrücklich erwünscht!
