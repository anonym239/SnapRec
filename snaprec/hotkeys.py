"""Eigene, globale Tastenkürzel.

Kürzel werden als Text gespeichert, z. B. "ctrl+alt+r" oder "win+shift+f9".
Unter Windows nutzt SnapRec die eingebaute Funktion RegisterHotKey (sehr
zuverlässig, meldet belegte Kürzel), unter Linux/macOS die Bibliothek pynput.
"""

import queue
import sys
import threading

IS_WINDOWS = sys.platform == "win32"

MODIFIERS = ("ctrl", "alt", "shift", "win")
MOD_LABELS = {"ctrl": "Strg", "alt": "Alt", "shift": "Shift", "win": "Win"}

# Name -> (Anzeige, Windows-Virtual-Key, pynput-Name)
SPECIAL_KEYS = {
    "space": ("Leertaste", 0x20, "<space>"),
    "print_screen": ("Druck", 0x2C, "<print_screen>"),
    "insert": ("Einfg", 0x2D, "<insert>"),
    "delete": ("Entf", 0x2E, "<delete>"),
    "home": ("Pos1", 0x24, "<home>"),
    "end": ("Ende", 0x23, "<end>"),
    "page_up": ("Bild ↑", 0x21, "<page_up>"),
    "page_down": ("Bild ↓", 0x22, "<page_down>"),
    "pause": ("Pause", 0x13, "<pause>"),
    "left": ("←", 0x25, "<left>"),
    "up": ("↑", 0x26, "<up>"),
    "right": ("→", 0x27, "<right>"),
    "down": ("↓", 0x28, "<down>"),
}
for _n in range(1, 25):
    SPECIAL_KEYS[f"f{_n}"] = (f"F{_n}", 0x6F + _n, f"<f{_n}>")

# Tk-Keysym -> Name
_TK_KEYSYMS = {
    "space": "space", "Print": "print_screen", "Insert": "insert", "Delete": "delete",
    "Home": "home", "End": "end", "Prior": "page_up", "Next": "page_down",
    "Pause": "pause", "Left": "left", "Up": "up", "Right": "right", "Down": "down",
}
_TK_MODIFIER_KEYSYMS = {
    "Control_L": "ctrl", "Control_R": "ctrl", "Shift_L": "shift", "Shift_R": "shift",
    "Alt_L": "alt", "Alt_R": "alt", "Meta_L": "alt", "Meta_R": "alt",
    "Super_L": "win", "Super_R": "win", "Win_L": "win", "Win_R": "win",
    "App": None, "Caps_Lock": None, "Num_Lock": None, "ISO_Level3_Shift": None,
}


class HotkeyError(ValueError):
    pass


def parse(combo):
    """'ctrl+alt+r' -> (frozenset({'ctrl','alt'}), 'r'). Wirft HotkeyError."""
    if not combo:
        raise HotkeyError("leer")
    parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
    mods = set()
    key = None
    for p in parts:
        if p in MODIFIERS:
            mods.add(p)
        elif key is None and (p in SPECIAL_KEYS or (len(p) == 1 and p.isalnum() and p.isascii())):
            key = p
        else:
            raise HotkeyError(f"Unbekannte Taste: {p}")
    if key is None:
        raise HotkeyError("Es fehlt eine normale Taste")
    if not mods and not (key.startswith("f") and len(key) > 1 or key in ("print_screen", "pause")):
        raise HotkeyError("Bitte mit Strg, Alt, Shift oder Win kombinieren")
    if mods == {"shift"} and not (key.startswith("f") and len(key) > 1):
        raise HotkeyError("Shift allein reicht nicht – bitte Strg, Alt oder Win dazunehmen")
    return frozenset(mods), key


def normalize(combo):
    mods, key = parse(combo)
    return "+".join([m for m in MODIFIERS if m in mods] + [key])


def label_parts(combo):
    """Für die Anzeige als Tasten: ['Strg', 'Alt', 'R']."""
    mods, key = parse(combo)
    name = SPECIAL_KEYS[key][0] if key in SPECIAL_KEYS else key.upper()
    return [MOD_LABELS[m] for m in MODIFIERS if m in mods] + [name]


def label(combo):
    try:
        return " + ".join(label_parts(combo))
    except HotkeyError:
        return ""


def to_pynput(combo):
    mods, key = parse(combo)
    names = {"ctrl": "<ctrl>", "alt": "<alt>", "shift": "<shift>", "win": "<cmd>"}
    key_name = SPECIAL_KEYS[key][2] if key in SPECIAL_KEYS else key
    return "+".join([names[m] for m in MODIFIERS if m in mods] + [key_name])


def to_windows(combo):
    """-> (Modifier-Flags, Virtual-Key) für RegisterHotKey."""
    mods, key = parse(combo)
    flags = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4, "win": 0x8}
    value = 0
    for m in mods:
        value |= flags[m]
    vk = SPECIAL_KEYS[key][1] if key in SPECIAL_KEYS else ord(key.upper())
    return value, vk


def key_from_tk_event(keysym, keycode):
    """Taste aus einem Tk-Ereignis ermitteln. None = reine Modifier-Taste."""
    if keysym in _TK_MODIFIER_KEYSYMS:
        return None
    if IS_WINDOWS and (0x30 <= keycode <= 0x39 or 0x41 <= keycode <= 0x5A):
        return chr(keycode).lower()     # unabhängig von Shift/Tastaturlayout
    if keysym in _TK_KEYSYMS:
        return _TK_KEYSYMS[keysym]
    if len(keysym) == 1 and keysym.isascii() and keysym.isalnum():
        return keysym.lower()
    if keysym.startswith("F") and keysym[1:].isdigit() and 1 <= int(keysym[1:]) <= 24:
        return keysym.lower()
    raise HotkeyError(f"Die Taste „{keysym}“ wird nicht unterstützt")


def modifiers_from_tk_state(state):
    mods = set()
    if state & 0x0001:
        mods.add("shift")
    if state & 0x0004:
        mods.add("ctrl")
    if IS_WINDOWS:
        if state & 0x20000:
            mods.add("alt")
    elif sys.platform == "darwin":
        if state & 0x0010:
            mods.add("alt")
        if state & 0x0008:
            mods.add("win")
    else:
        if state & 0x0008:
            mods.add("alt")
        if state & 0x0040:
            mods.add("win")
    return mods


def modifier_from_keysym(keysym):
    return _TK_MODIFIER_KEYSYMS.get(keysym)


# ---- Registrieren --------------------------------------------------------

class _WindowsBackend(threading.Thread):
    WM_HOTKEY, WM_QUIT = 0x0312, 0x0012

    def __init__(self, bindings, fire):
        super().__init__(daemon=True)
        self.bindings = bindings
        self.fire = fire
        self.errors = {}
        self.ready = threading.Event()
        self.thread_id = None

    def run(self):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0x400, 0x400, 0)  # Warteschlange anlegen
        ids = {}
        for i, (action, combo) in enumerate(self.bindings.items(), start=1):
            mods, vk = to_windows(combo)
            if user32.RegisterHotKey(None, i, mods | 0x4000, vk):  # 0x4000 = MOD_NOREPEAT
                ids[i] = action
            else:
                self.errors[action] = "Schon von einem anderen Programm belegt"
        self.ready.set()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == self.WM_HOTKEY and msg.wParam in ids:
                self.fire(ids[msg.wParam])
        for i in ids:
            user32.UnregisterHotKey(None, i)

    def stop(self):
        import ctypes
        if self.thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, self.WM_QUIT, 0, 0)
        self.join(timeout=2)


class _PynputBackend:
    def __init__(self, bindings, fire):
        self.errors = {}
        self.listener = None
        try:
            from pynput import keyboard
        except Exception:  # z. B. Wayland oder kein Bildschirm
            self.errors = {a: "Globale Tastenkürzel werden hier nicht unterstützt" for a in bindings}
            return
        mapping = {}
        for action, combo in bindings.items():
            mapping[to_pynput(combo)] = (lambda a=action: fire(a))
        try:
            self.listener = keyboard.GlobalHotKeys(mapping)
            self.listener.daemon = True
            self.listener.start()
        except Exception as exc:
            self.errors = {a: f"Nicht verfügbar: {exc}" for a in bindings}
            self.listener = None

    def stop(self):
        if self.listener:
            self.listener.stop()


class HotkeyManager:
    """Registriert Kürzel und liefert ausgelöste Aktionen über poll()."""

    def __init__(self):
        self.events = queue.Queue()
        self._backend = None
        self.errors = {}

    def apply(self, hotkeys):
        """hotkeys: {aktion: kürzel oder ''}. Gibt {aktion: fehlertext} zurück."""
        self.stop()
        bindings = {}
        self.errors = {}
        for action, combo in hotkeys.items():
            if not combo:
                continue
            try:
                bindings[action] = normalize(combo)
            except HotkeyError as exc:
                self.errors[action] = str(exc)
        if bindings:
            if IS_WINDOWS:
                backend = _WindowsBackend(bindings, self.events.put)
                backend.start()
                backend.ready.wait(2)
            else:
                backend = _PynputBackend(bindings, self.events.put)
            self._backend = backend
            self.errors.update(backend.errors)
        return dict(self.errors)

    def poll(self):
        actions = []
        while True:
            try:
                actions.append(self.events.get_nowait())
            except queue.Empty:
                return actions

    def stop(self):
        if self._backend:
            self._backend.stop()
            self._backend = None
