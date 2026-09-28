"""Hauptfenster und Ablauf: Auswahl → Countdown → Aufnahme → Speichern."""

import argparse
import datetime
import os
import sys
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

try:
    import customtkinter as ctk
    import imageio_ffmpeg  # noqa: F401
    import mss  # noqa: F401
    from PIL import ImageTk
except ImportError as exc:  # pragma: no cover - nur Hinweis für Nutzer
    print(f"Fehlendes Paket: {exc.name}\nBitte installieren mit:  pip install -r requirements.txt")
    sys.exit(1)

from snaprec import APP_NAME, VERSION, hotkeys, theme
from snaprec.hotkeys import HotkeyManager
from snaprec.overlay import SelectionOverlay
from snaprec.recorder import Recorder
from snaprec.utils import (IS_WINDOWS, enable_dpi_awareness, format_size, format_time,
                           load_config, open_path, save_config, set_alpha, short_path)
from snaprec.widgets import ControlBar, RegionFrame

COUNTDOWN_VALUES = [0, 3, 5, 10]


def font(size, weight="normal"):
    return ctk.CTkFont(theme.FONT, size, weight)


def countdown_label(sec):
    return "Aus" if sec == 0 else f"{sec} s"


class App:
    def __init__(self, root, cfg, save_settings=True):
        self.root = root
        self.cfg = cfg
        self.save_settings = save_settings
        self.recorder = None
        self.overlay = None
        self.frame = None
        self.bar = None
        self.last_file = None
        self.settings_window = None
        self.intro_window = None
        self._cursor = None
        self._region = None
        self._ico_path = None

        self.hotkeys = HotkeyManager()
        self.hotkey_errors = {}

        root.title(APP_NAME)
        root.resizable(False, False)
        root.configure(fg_color=theme.BG)
        self.apply_icon(root)
        self._build_ui()
        root.bind("<Control-n>", lambda e: self.new_recording())
        root.bind("<F1>", lambda e: self.show_intro())
        root.protocol("WM_DELETE_WINDOW", self.quit)

        self.apply_hotkeys()
        self._poll_hotkeys()

        set_alpha(root, 0.0)
        root.after(30, lambda: theme.animate(root, 260, lambda t: set_alpha(root, t)))
        if not cfg.get("intro_seen"):
            root.after(500, self.show_intro)

    # ---- Oberfläche --------------------------------------------------------
    def apply_icon(self, win):
        """Eigenes Logo statt Standard-Symbol (auch in der Taskleiste)."""
        if not hasattr(self, "_icon_photo"):
            self._icon_photo = ImageTk.PhotoImage(theme.logo_image(64))
        try:
            win.iconphoto(False, self._icon_photo)
        except tk.TclError:
            pass
        if IS_WINDOWS:
            if not self._ico_path:
                path = os.path.join(tempfile.gettempdir(), "snaprec_icon.ico")
                try:
                    theme.logo_image(256).save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                                            (64, 64), (128, 128), (256, 256)])
                    self._ico_path = path
                except OSError:
                    return
            # customtkinter setzt nach 200 ms sein eigenes Symbol – danach überschreiben
            win.after(260, lambda: win.winfo_exists() and win.iconbitmap(self._ico_path))

    def _build_ui(self):
        root = self.root
        wrap = ctk.CTkFrame(root, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=20, pady=18)

        # Kopfzeile
        head = ctk.CTkFrame(wrap, fg_color="transparent")
        head.pack(fill="x")
        logo = theme.logo_image(96)
        ctk.CTkLabel(head, text="", image=ctk.CTkImage(logo, logo, size=(44, 44))).pack(side="left")
        titles = ctk.CTkFrame(head, fg_color="transparent")
        titles.pack(side="left", padx=12)
        ctk.CTkLabel(titles, text=APP_NAME, font=font(22, "bold"), text_color=theme.TEXT,
                     height=26).pack(anchor="w")
        ctk.CTkLabel(titles, text="Bildschirmbereich aufnehmen", font=font(12),
                     text_color=theme.MUTED, height=16).pack(anchor="w")
        icon_btn = dict(text="", width=38, height=38, corner_radius=12, fg_color=theme.SURFACE_2,
                        hover_color=theme.SURFACE_3)
        ctk.CTkButton(head, image=theme.ctk_icon("gear", 18, theme.MUTED), command=self.show_settings,
                      **icon_btn).pack(side="right")
        ctk.CTkButton(head, image=theme.ctk_icon("help", 18, theme.MUTED), command=self.show_intro,
                      **icon_btn).pack(side="right", padx=8)

        # Großer Aufnahme-Knopf + Vollbild
        actions = ctk.CTkFrame(wrap, fg_color="transparent")
        actions.pack(fill="x", pady=(20, 6))
        self.full_btn = ctk.CTkButton(
            actions, text="", image=theme.ctk_icon("fullscreen", 22), width=58, height=58,
            corner_radius=16, fg_color=theme.SURFACE_2, hover_color=theme.SURFACE_3,
            command=lambda: self.new_recording(full=True))
        self.full_btn.pack(side="right", padx=(10, 0))
        self.new_btn = ctk.CTkButton(
            actions, text="  Neue Aufnahme", image=theme.ctk_icon("record", 20, "#ffffff"),
            height=58, corner_radius=16, fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            text_color="#ffffff", font=font(17, "bold"), command=self.new_recording)
        self.new_btn.pack(side="left", fill="x", expand=True)
        hints = ctk.CTkFrame(wrap, fg_color="transparent")
        hints.pack(fill="x")
        self.hint_new = ctk.CTkLabel(hints, text="", font=font(11), text_color=theme.MUTED, height=18)
        self.hint_new.pack(side="left", expand=True)
        self.hint_full = ctk.CTkLabel(hints, text="Vollbild", font=font(11), text_color=theme.MUTED,
                                      width=58, height=18)
        self.hint_full.pack(side="right", padx=(10, 0))

        # Countdown
        cd = ctk.CTkFrame(wrap, fg_color=theme.SURFACE, corner_radius=16, border_width=1,
                          border_color=theme.BORDER)
        cd.pack(fill="x", pady=(16, 0))
        ctk.CTkLabel(cd, text="Countdown", font=font(13, "bold"), text_color=theme.TEXT).pack(
            side="left", padx=(18, 12), pady=14)
        values = COUNTDOWN_VALUES if self.cfg["countdown"] in COUNTDOWN_VALUES else sorted(
            COUNTDOWN_VALUES + [self.cfg["countdown"]])
        self.countdown = ctk.CTkSegmentedButton(
            cd, values=[countdown_label(v) for v in values], font=font(13), height=34,
            selected_color=theme.ACCENT, selected_hover_color=theme.ACCENT_HOVER,
            unselected_color=theme.SURFACE_2, unselected_hover_color=theme.SURFACE_3,
            fg_color=theme.SURFACE_2, command=self._countdown_changed)
        self.countdown.set(countdown_label(self.cfg["countdown"]))
        self.countdown.pack(side="right", padx=14, pady=12, fill="x", expand=True)

        # Ergebnis-Karte (erscheint nach der Aufnahme)
        self.result = ctk.CTkFrame(wrap, fg_color=theme.SURFACE, corner_radius=16, border_width=1,
                                   border_color=theme.BORDER)
        top = ctk.CTkFrame(self.result, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 8))
        self.result_icon = ctk.CTkLabel(top, text="", image=theme.ctk_icon("check_circle", 40))
        self.result_icon.pack(side="left")
        texts = ctk.CTkFrame(top, fg_color="transparent")
        texts.pack(side="left", padx=12, fill="x", expand=True)
        self.result_title = ctk.CTkLabel(texts, text="Aufnahme gespeichert", font=font(14, "bold"),
                                         text_color=theme.TEXT, anchor="w", height=20)
        self.result_title.pack(fill="x")
        self.result_info = ctk.CTkLabel(texts, text="", font=font(12), text_color=theme.MUTED,
                                        anchor="w", height=18)
        self.result_info.pack(fill="x")
        btns = ctk.CTkFrame(self.result, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=(0, 14))
        small = dict(height=34, corner_radius=10, font=font(12), fg_color=theme.SURFACE_2,
                     hover_color=theme.SURFACE_3)
        ctk.CTkButton(btns, text=" Abspielen", image=theme.ctk_icon("play", 12), command=self.play_last,
                      **small).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(btns, text=" Ordner öffnen", image=theme.ctk_icon("folder", 14),
                      command=lambda: self._open(self.cfg["output_dir"]), **small).pack(
            side="left", fill="x", expand=True, padx=(8, 0))

        # Speichern-Fortschritt
        self.saving = ctk.CTkFrame(wrap, fg_color="transparent")
        ctk.CTkLabel(self.saving, text="Video wird gespeichert …", font=font(12),
                     text_color=theme.MUTED).pack(anchor="w")
        self.progress = ctk.CTkProgressBar(self.saving, mode="indeterminate", height=6,
                                           progress_color=theme.ACCENT, fg_color=theme.SURFACE_2)
        self.progress.pack(fill="x", pady=(4, 0))

        # Fußzeile
        self.footer = ctk.CTkButton(
            wrap, text="", image=theme.ctk_icon("folder", 13, theme.MUTED), height=28,
            fg_color="transparent", hover_color=theme.SURFACE, text_color=theme.MUTED,
            font=font(11), anchor="w", command=lambda: self._open(self.cfg["output_dir"]))
        self.footer.pack(fill="x", pady=(14, 0))
        self.status = ctk.CTkLabel(wrap, text="", font=font(11), text_color=theme.MUTED, height=14)
        self.refresh_footer()
        self.refresh_hints()

        root.update_idletasks()
        root.minsize(440, 0)

    def refresh_footer(self):
        self.footer.configure(text=f"  {short_path(self.cfg['output_dir'], 44)}")

    def refresh_hints(self):
        combo = self.cfg["hotkeys"].get("toggle")
        self.hint_new.configure(text=f"oder {hotkeys.label(combo)}" if combo else "")
        full = self.cfg["hotkeys"].get("fullscreen")
        self.hint_full.configure(text=hotkeys.label(full).replace(" + ", "+") if full else "Vollbild")

    def show_message(self, text, error=False):
        self.status.configure(text=text, text_color=theme.REC if error else theme.MUTED)
        self.status.pack(fill="x", pady=(6, 0))
        self.root.after(5000, lambda: self.status.pack_forget() if self.status.winfo_exists() else None)

    def _countdown_changed(self, value):
        self.cfg["countdown"] = 0 if value == "Aus" else int(value.split()[0])
        self.save()

    def save(self):
        if self.save_settings:
            save_config(self.cfg)

    def _open(self, path):
        try:
            if not os.path.exists(path):
                os.makedirs(path, exist_ok=True)
            open_path(path)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Konnte nicht öffnen:\n{exc}", parent=self.root)

    def play_last(self):
        if self.last_file:
            self._open(self.last_file)

    def show_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            self.settings_window.focus_force()
            return
        from snaprec.settings import SettingsWindow
        self.settings_window = SettingsWindow(self)

    def show_intro(self):
        if self.intro_window and self.intro_window.winfo_exists():
            self.intro_window.lift()
            return
        from snaprec.intro import show_intro

        def closed():
            self.intro_window = None
            if not self.cfg.get("intro_seen"):
                self.cfg["intro_seen"] = True
                self.save()
        self.intro_window = show_intro(self.root, closed)
        self.apply_icon(self.intro_window)

    # ---- Tastenkürzel -------------------------------------------------------
    def apply_hotkeys(self):
        self.hotkey_errors = self.hotkeys.apply(self.cfg["hotkeys"])
        return self.hotkey_errors

    def _poll_hotkeys(self):
        for action in self.hotkeys.poll():
            self.on_hotkey(action)
        self.root.after(50, self._poll_hotkeys)

    def on_hotkey(self, action):
        if self.settings_window and self.settings_window.capturing:
            return
        if action == "toggle":
            if self.recorder:
                self.stop_recording()
            elif not self.overlay:
                self.new_recording()
        elif action == "pause":
            if self.recorder:
                self.toggle_pause()
        elif action == "fullscreen":
            if not self.recorder and not self.overlay:
                self.new_recording(full=True)

    # ---- Ablauf -------------------------------------------------------------
    def new_recording(self, full=False):
        if self.recorder or self.overlay:
            return
        for win in (self.settings_window, self.intro_window):
            if win and win.winfo_exists():
                win.withdraw()
        self.root.withdraw()
        # kurz warten, bis die Fenster wirklich weg sind, dann Screenshot
        self.root.after(250, lambda: self._open_overlay(full))

    def _open_overlay(self, full):
        self.overlay = SelectionOverlay(self.root, self.cfg["countdown"], self._on_selected,
                                        preselect_monitor=full)

    def _on_selected(self, region):
        self.overlay = None
        if not region:
            self._back_to_main()
            return
        self._region = region
        # Overlay ist zu – kurz warten, damit es sicher nicht im Video landet
        self.root.after(120, self._start_recording)

    def _start_recording(self):
        out_dir = Path(self.cfg["output_dir"])
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"Ordner kann nicht angelegt werden:\n{exc}")
            self._back_to_main()
            return
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = str(out_dir / f"Aufnahme_{stamp}.mp4")

        self.frame = RegionFrame(self.root, self._region, theme.ACCENT)
        self.frame.set_color(theme.REC)
        stop_combo = self.cfg["hotkeys"].get("toggle")
        self.bar = ControlBar(self.root, self._region, self.toggle_pause, self.stop_recording,
                              stop_hint=hotkeys.label(stop_combo) if stop_combo else "")
        cursor = self._get_cursor if self.cfg["cursor"] else None
        self.recorder = Recorder(self._region, self.cfg["fps"], path, cursor)
        self.recorder.start()
        self._track_cursor()
        self._update_bar()

    def _track_cursor(self):
        """Mausposition im Hauptthread lesen (Tk ist nicht threadsicher)."""
        if not self.recorder:
            return
        try:
            self._cursor = self.root.winfo_pointerxy()
        except tk.TclError:
            self._cursor = None
        self.root.after(15, self._track_cursor)

    def _get_cursor(self):
        return self._cursor

    def _update_bar(self):
        rec = self.recorder
        if not rec:
            return
        if rec.error or not rec.is_alive():
            self.stop_recording()
            return
        self.bar.update_state(rec.elapsed, rec.paused)
        self.root.after(200, self._update_bar)

    def toggle_pause(self):
        if self.recorder:
            self.recorder.set_paused(not self.recorder.paused)
            self.frame.set_color(theme.PAUSE if self.recorder.paused else theme.REC)
            self.bar.update_state(self.recorder.elapsed, self.recorder.paused)

    def stop_recording(self):
        rec = self.recorder
        if not rec:
            return
        rec.stop()
        self._cleanup_windows()
        self.result.pack_forget()
        self.saving.pack(fill="x", pady=(16, 0), before=self.footer)
        self.progress.start()
        self._back_to_main()

        def wait():
            if rec.is_alive():
                self.root.after(100, wait)
                return
            self.recorder = None
            self.progress.stop()
            self.saving.pack_forget()
            if rec.error:
                messagebox.showerror(APP_NAME, f"Aufnahme fehlgeschlagen:\n{rec.error}", parent=self.root)
            else:
                self.last_file = rec.path
                self._show_result(rec)
        wait()

    def _show_result(self, rec):
        try:
            size = format_size(os.path.getsize(rec.path))
        except OSError:
            size = ""
        r = rec.region
        self.result_info.configure(
            text=f"{Path(rec.path).name}\n{format_time(rec.elapsed)}  ·  {r['width']}×{r['height']}  ·  {size}",
            height=36, justify="left")
        self.result.pack(fill="x", pady=(16, 0), before=self.footer)
        # kleine Animation: Karte leuchtet kurz grün auf
        theme.animate(self.result, 900, lambda t: self.result.configure(
            border_color=theme.mix(theme.OK, theme.BORDER, t)))

    def _cleanup_windows(self):
        if self.bar:
            self.bar.destroy()
            self.bar = None
        if self.frame:
            self.frame.destroy()
            self.frame = None

    def _back_to_main(self):
        self.root.deiconify()
        self.root.lift()
        for win in (self.settings_window, self.intro_window):
            if win and win.winfo_exists():
                win.deiconify()

    def quit(self):
        if self.recorder:
            self.recorder.stop()
            self.recorder.join(timeout=10)
        self.hotkeys.stop()
        self.root.destroy()


def selftest(report_path):
    """Prüft die fertige .exe ohne Fenster: Pakete, Grafik, Video schreiben."""
    import traceback
    lines, ok = [f"{APP_NAME} {VERSION}"], True
    try:
        from snaprec import intro
        theme.logo_image(64)
        theme.countdown_badge(120, 3, 0.5)
        intro.render_scene(1, 1.0)
        lines.append("grafik: ok")
        path = os.path.join(tempfile.gettempdir(), "snaprec_selftest.mp4")
        writer = imageio_ffmpeg.write_frames(path, (64, 48), fps=10, codec="libx264",
                                             macro_block_size=2)
        writer.send(None)
        for i in range(10):
            writer.send(bytes([i * 20 % 256]) * (64 * 48 * 3))
        writer.close()
        lines.append(f"video: ok ({os.path.getsize(path)} Bytes)")
        os.remove(path)
    except Exception:
        ok = False
        lines.append(traceback.format_exc())
    try:
        from snaprec.utils import virtual_screen
        lines.append(f"bildschirm: {virtual_screen()[0]}")
    except Exception as exc:  # auf Servern ohne Bildschirm nicht schlimm
        lines.append(f"bildschirm: nicht verfügbar ({exc})")
    lines.append("ERGEBNIS: " + ("OK" if ok else "FEHLER"))
    Path(report_path).write_text("\n".join(lines), encoding="utf-8")
    return 0 if ok else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=f"{APP_NAME} – Bildschirmbereich aufnehmen")
    parser.add_argument("-c", "--countdown", type=int, help="Countdown in Sekunden (0 = keiner)")
    parser.add_argument("--fps", type=int, help="Bilder pro Sekunde (Standard 30)")
    parser.add_argument("-o", "--output", help="Ordner für die Videos")
    parser.add_argument("--no-cursor", action="store_true", help="Mauszeiger nicht aufnehmen")
    parser.add_argument("-s", "--start", action="store_true", help="direkt mit der Bereichsauswahl starten")
    parser.add_argument("-f", "--fullscreen", action="store_true", help="direkt den ganzen Bildschirm aufnehmen")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    parser.add_argument("--selftest", metavar="DATEI", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.selftest:
        sys.exit(selftest(args.selftest))

    cfg = load_config()
    if args.countdown is not None:
        cfg["countdown"] = max(0, args.countdown)
    if args.fps:
        cfg["fps"] = max(1, min(args.fps, 120))
    if args.output:
        cfg["output_dir"] = args.output
    if args.no_cursor:
        cfg["cursor"] = False

    enable_dpi_awareness()
    if IS_WINDOWS:
        try:  # eigenes Symbol in der Taskleiste statt Python-Symbol
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SnapRec.App")
        except Exception:
            pass
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    theme.init_fonts(root)
    app = App(root, cfg)
    if args.start or args.fullscreen:
        root.after(400, lambda: app.new_recording(full=args.fullscreen))
    root.mainloop()


if __name__ == "__main__":
    main()
