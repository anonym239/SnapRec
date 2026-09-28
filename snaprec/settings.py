"""Einstellungsfenster: Aufnahme, Speicherort und eigene Tastenkürzel."""

import tkinter as tk
import webbrowser
from tkinter import filedialog

import customtkinter as ctk

from snaprec import APP_NAME, REPO_URL, VERSION, hotkeys, theme
from snaprec.utils import DEFAULT_HOTKEYS, set_alpha, short_path

ACTIONS = [
    ("toggle", "Aufnahme starten / stoppen"),
    ("pause", "Pause / Weiter"),
    ("fullscreen", "Ganzen Bildschirm aufnehmen"),
]
ACTION_NAMES = dict(ACTIONS)
FPS_VALUES = ["15", "24", "30", "60"]


def font(size, weight="normal"):
    return ctk.CTkFont(theme.FONT, size, weight)


def keycaps_image(combo, height=24):
    parts = hotkeys.label_parts(combo)
    img = theme.keycaps(parts, height * 2)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(img.width // 2, height))


def card(master, title, subtitle=None, icon=None):
    frame = ctk.CTkFrame(master, fg_color=theme.SURFACE, corner_radius=16,
                         border_width=1, border_color=theme.BORDER)
    head = ctk.CTkFrame(frame, fg_color="transparent")
    head.pack(fill="x", padx=18, pady=(14, 4))
    if icon:
        ctk.CTkLabel(head, text="", image=theme.ctk_icon(icon, 18, theme.ACCENT)).pack(side="left", padx=(0, 8))
    ctk.CTkLabel(head, text=title, font=font(15, "bold"), text_color=theme.TEXT).pack(side="left")
    if subtitle:
        ctk.CTkLabel(frame, text=subtitle, font=font(12), text_color=theme.MUTED,
                     anchor="w", justify="left", wraplength=440).pack(fill="x", padx=18, pady=(0, 6))
    return frame


def row(master, label):
    r = ctk.CTkFrame(master, fg_color="transparent")
    r.pack(fill="x", padx=18, pady=6)
    ctk.CTkLabel(r, text=label, font=font(13), text_color=theme.TEXT).pack(side="left")
    return r


class HotkeyRow:
    """Eine Zeile: Aktion + Knopf, der die Tastenkombination aufnimmt."""

    def __init__(self, settings, master, action, name):
        self.settings = settings
        self.action = action
        r = self.row_frame = row(master, name)
        self.clear_btn = ctk.CTkButton(
            r, text="", image=theme.ctk_icon("close", 12, theme.MUTED), width=30, height=30,
            corner_radius=8, fg_color="transparent", hover_color=theme.SURFACE_2,
            command=self.clear)
        self.clear_btn.pack(side="right", padx=(4, 0))
        self.button = ctk.CTkButton(
            r, text="", width=150, height=36, corner_radius=10, fg_color=theme.SURFACE_2,
            hover_color=theme.SURFACE_3, border_width=1, border_color=theme.BORDER,
            text_color=theme.TEXT, font=font(12), command=self.start_capture)
        self.button.pack(side="right")
        self.error = ctk.CTkLabel(master, text="", font=font(11), text_color=theme.REC,
                                  anchor="e", height=16)
        self.refresh()

    def set_error(self, text, color=theme.REC):
        if text:
            self.error.configure(text=text, text_color=color)
            self.error.pack(fill="x", padx=18, after=self.row_frame)
        else:
            self.error.pack_forget()

    @property
    def combo(self):
        return self.settings.cfg["hotkeys"].get(self.action, "")

    def refresh(self, error=None):
        combo = self.combo
        if combo:
            try:
                self.button.configure(image=keycaps_image(combo), text="", text_color=theme.TEXT)
            except hotkeys.HotkeyError:
                self.button.configure(image=None, text="Ungültig")
        else:
            self.button.configure(image=None, text="Kein Kürzel", text_color=theme.MUTED)
        self.button.configure(border_color=theme.BORDER)
        self.set_error(error)

    def start_capture(self):
        self.settings.begin_capture(self)
        self.button.configure(image=None, text="Tasten drücken …", text_color=theme.TEXT,
                              border_color=theme.ACCENT)
        self.set_error("Esc = abbrechen   ·   Entf = Kürzel entfernen", theme.MUTED)

    def show_partial(self, mods):
        parts = [hotkeys.MOD_LABELS[m] for m in hotkeys.MODIFIERS if m in mods]
        self.button.configure(text=" + ".join(parts) + " + …" if parts else "Tasten drücken …")

    def clear(self):
        self.settings.set_hotkey(self.action, "")


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app.root, fg_color=theme.BG)
        self.app = app
        self.cfg = app.cfg
        self.title(f"{APP_NAME} – Einstellungen")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.capturing = None
        self.pressed = set()
        app.apply_icon(self)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=(18, 8))
        ctk.CTkLabel(body, text="Einstellungen", font=font(22, "bold"),
                     text_color=theme.TEXT).pack(anchor="w", pady=(0, 12))

        # --- Aufnahme ---
        c = card(body, "Aufnahme", icon="record")
        c.pack(fill="x", pady=(0, 12))
        r = row(c, "Bildrate")
        self.fps = ctk.CTkSegmentedButton(
            r, values=[f"{v} fps" for v in FPS_VALUES], font=font(12), height=32,
            selected_color=theme.ACCENT, selected_hover_color=theme.ACCENT_HOVER,
            unselected_color=theme.SURFACE_2, unselected_hover_color=theme.SURFACE_3,
            fg_color=theme.SURFACE_2, command=self._fps_changed)
        self.fps.set(f"{self.cfg['fps']} fps")
        self.fps.pack(side="right")
        r = row(c, "Mauszeiger mit aufnehmen")
        self.cursor = ctk.CTkSwitch(r, text="", progress_color=theme.ACCENT, width=46,
                                    command=self._cursor_changed)
        if self.cfg["cursor"]:
            self.cursor.select()
        self.cursor.pack(side="right")
        r = row(c, "Speicherort")
        ctk.CTkButton(r, text="Ändern", width=80, height=30, corner_radius=8, font=font(12),
                      fg_color=theme.SURFACE_2, hover_color=theme.SURFACE_3,
                      command=self._choose_folder).pack(side="right")
        self.folder = ctk.CTkLabel(r, text=short_path(self.cfg["output_dir"], 30), font=font(12),
                                   text_color=theme.MUTED)
        self.folder.pack(side="right", padx=10)
        ctk.CTkFrame(c, fg_color="transparent", height=8).pack()

        # --- Tastenkürzel ---
        c = card(body, "Tastenkürzel", "Klick auf ein Kürzel und drück deine Wunsch-Kombination. "
                 "Die Kürzel funktionieren überall – auch wenn SnapRec im Hintergrund ist.",
                 icon="keyboard")
        c.pack(fill="x", pady=(0, 12))
        self.rows = {a: HotkeyRow(self, c, a, n) for a, n in ACTIONS}
        foot = ctk.CTkFrame(c, fg_color="transparent")
        foot.pack(fill="x", padx=18, pady=(2, 12))
        ctk.CTkButton(foot, text="Standard wiederherstellen", width=10, height=28, corner_radius=8,
                      font=font(12), fg_color="transparent", hover_color=theme.SURFACE_2,
                      text_color=theme.ACCENT, command=self._reset_hotkeys).pack(side="left")

        # --- Über ---
        c = card(body, f"{APP_NAME} {VERSION}", "Kostenlos & Open Source (MIT-Lizenz).", icon="help")
        c.pack(fill="x")
        r = ctk.CTkFrame(c, fg_color="transparent")
        r.pack(fill="x", padx=18, pady=(0, 14))
        ctk.CTkButton(r, text="Einführung ansehen", height=32, corner_radius=8, font=font(12),
                      fg_color=theme.SURFACE_2, hover_color=theme.SURFACE_3,
                      command=self._show_intro).pack(side="left")
        ctk.CTkButton(r, text="GitHub", height=32, width=80, corner_radius=8, font=font(12),
                      fg_color=theme.SURFACE_2, hover_color=theme.SURFACE_3,
                      command=lambda: webbrowser.open(REPO_URL)).pack(side="left", padx=8)

        ctk.CTkButton(self, text="Fertig", height=40, corner_radius=12, font=font(14, "bold"),
                      fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      command=self.close).pack(fill="x", padx=20, pady=(4, 20))

        self.bind("<KeyPress>", self._key_press)
        self.bind("<KeyRelease>", self._key_release)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.show_errors(app.hotkey_errors)

        self.update_idletasks()
        x = app.root.winfo_rootx() + app.root.winfo_width() + 16
        y = max(0, app.root.winfo_rooty() - 40)
        if x + self.winfo_reqwidth() > self.winfo_screenwidth():
            x = max(0, self.winfo_screenwidth() // 2 - self.winfo_reqwidth() // 2)
        self.wm_geometry(f"+{x}+{y}")
        set_alpha(self, 0.0)
        theme.animate(self, 200, lambda t: set_alpha(self, t))
        self.after(60, self.focus_force)

    # ---- allgemeine Einstellungen ------------------------------------------
    def _fps_changed(self, value):
        self.cfg["fps"] = int(value.split()[0])
        self.app.save()

    def _cursor_changed(self):
        self.cfg["cursor"] = bool(self.cursor.get())
        self.app.save()

    def _choose_folder(self):
        folder = filedialog.askdirectory(parent=self, initialdir=self.cfg["output_dir"],
                                         title="Speicherort für Aufnahmen")
        if folder:
            self.cfg["output_dir"] = folder
            self.folder.configure(text=short_path(folder, 30))
            self.app.save()
            self.app.refresh_footer()

    def _show_intro(self):
        self.close()
        self.app.show_intro()

    # ---- Tastenkürzel -----------------------------------------------------
    def begin_capture(self, hotkey_row):
        if self.capturing and self.capturing is not hotkey_row:
            self.capturing.refresh()
        self.capturing = hotkey_row
        self.pressed = set()
        self.app.hotkeys.stop()   # sonst löst die alte Kombination beim Drücken aus
        self.focus_force()

    def end_capture(self):
        if self.capturing:
            self.capturing = None
            self.pressed = set()
            self.app.apply_hotkeys()
            self.show_errors(self.app.hotkey_errors)

    def _key_press(self, event):
        row_ = self.capturing
        if not row_:
            return
        mod = hotkeys.modifier_from_keysym(event.keysym)
        if mod:
            self.pressed.add(mod)
            row_.show_partial(self.pressed | hotkeys.modifiers_from_tk_state(event.state))
            return "break"
        if event.keysym in hotkeys._TK_MODIFIER_KEYSYMS:  # Caps Lock usw.
            return "break"
        mods = self.pressed | hotkeys.modifiers_from_tk_state(event.state)
        if event.keysym == "Escape" and not mods:
            self.end_capture()
            return "break"
        if event.keysym in ("BackSpace", "Delete") and not mods:
            self.set_hotkey(row_.action, "")
            return "break"
        try:
            key = hotkeys.key_from_tk_event(event.keysym, event.keycode)
            combo = "+".join([m for m in hotkeys.MODIFIERS if m in mods] + [key])
            combo = hotkeys.normalize(combo)
        except hotkeys.HotkeyError as exc:
            row_.set_error(str(exc))
            return "break"
        for other, other_combo in self.cfg["hotkeys"].items():
            if other != row_.action and other_combo and hotkeys.normalize(other_combo) == combo:
                row_.set_error(f"Schon vergeben für „{ACTION_NAMES[other]}“")
                return "break"
        self.set_hotkey(row_.action, combo)
        return "break"

    def _key_release(self, event):
        mod = hotkeys.modifier_from_keysym(event.keysym)
        if mod:
            self.pressed.discard(mod)
            if self.capturing:
                self.capturing.show_partial(self.pressed)

    def set_hotkey(self, action, combo):
        self.cfg["hotkeys"][action] = combo
        self.app.save()
        self.rows[action].refresh()
        self.capturing = self.rows[action]
        self.end_capture()
        self.app.refresh_hints()
        self._flash(self.rows[action])

    def _flash(self, hotkey_row):
        btn = hotkey_row.button
        theme.animate(btn, 500, lambda t: btn.configure(border_color=theme.mix(theme.OK, theme.BORDER, t)))

    def show_errors(self, errors):
        for action, r in self.rows.items():
            r.refresh(errors.get(action))

    def _reset_hotkeys(self):
        self.cfg["hotkeys"] = dict(DEFAULT_HOTKEYS)
        self.app.save()
        self.app.apply_hotkeys()
        self.show_errors(self.app.hotkey_errors)
        self.app.refresh_hints()

    def close(self):
        if self.capturing:
            self.end_capture()
        self.app.settings_window = None
        try:
            self.destroy()
        except tk.TclError:
            pass
