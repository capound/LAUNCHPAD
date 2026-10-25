#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LAUNCHPAD
One window for the apps, games, folders, files, links, actions and project
notes you use most, so nothing you're working on drops out of sight.

Windows 11 · Python 3.10+ · PySide6
Run:  pythonw launchpad.pyw            (normal)
      pythonw launchpad.pyw --tray     (start hidden in the tray)
      pythonw launchpad.pyw --install  (create desktop shortcut + start with Windows)
"""
from __future__ import annotations

import base64
import ctypes
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zlib
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import (QDate, QDir, QFileInfo, QMimeData, QObject, QPoint, QPointF, QRect,
                            QRectF, QSize, Qt, QTimer, QUrl, Signal)
from PySide6.QtGui import (QAction, QColor, QDrag, QFont, QFontMetricsF, QIcon,
                           QImage, QKeySequence, QPainter, QPen, QPixmap,
                           QPolygonF, QShortcut)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup,
                               QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
                               QFileDialog, QFileIconProvider, QFrame,
                               QGridLayout, QHBoxLayout, QInputDialog,
                               QKeySequenceEdit, QLabel, QLayout, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow,
                               QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                               QRadioButton, QScrollArea, QSizePolicy, QSlider,
                               QSplitter, QStackedWidget, QSystemTrayIcon,
                               QToolButton, QVBoxLayout, QWidget)

IS_WIN = sys.platform == "win32"
APP_NAME = "Launchpad"
APP_ID = "callum.launchpad.1"
VERSION = "3.0"
SERVER_NAME = "LaunchpadSingleInstance-v1"
DEFAULT_HOTKEY = "Ctrl+Shift+Space"
MONO_FAMILIES = ["Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Courier New"]

CATEGORIES = [("apps", "APPS"), ("games", "GAMES"), ("folders", "FOLDERS"),
              ("files", "FILES"), ("links", "LINKS"), ("actions", "ACTIONS")]
CAT_NAMES = dict(CATEGORIES)
APP_EXT = {".exe", ".lnk", ".bat", ".cmd", ".appref-ms", ".msc", ".ps1", ".com", ".jar"}
MIME_ITEM = "application/x-launchpad-item"
GAME_URL_PREFIXES = ("steam://", "com.epicgames.launcher://", "uplay://", "battlenet://",
                     "riotclient://", "origin://", "heroic://", "goggalaxy://")


# ============================================================ helpers
def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def data_dir() -> Path:
    override = os.environ.get("LAUNCHPAD_DATA_DIR")
    if override:
        p = Path(override)
    elif IS_WIN:
        p = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
    else:
        p = Path.home() / ".launchpad"
    p.mkdir(parents=True, exist_ok=True)
    return p


def now() -> float:
    return time.time()


def new_id() -> str:
    return uuid.uuid4().hex[:10]


def expand(t: str) -> str:
    return os.path.expandvars(os.path.expanduser((t or "").strip().strip('"')))


def is_url(t: str) -> bool:
    # scheme of 2+ chars, so "C:\..." is never treated as a URL
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9+.\-]+:", t or ""))


def is_web(t: str) -> bool:
    return (t or "").lower().startswith(("http://", "https://"))


def step_exists(s: dict) -> bool:
    t = expand(s.get("target", ""))
    if not t:
        return False
    if is_url(t):
        return True
    if "\\" not in t and "/" not in t:   # bare command like "notepad"
        return True
    return os.path.exists(t)


def target_exists(item: dict) -> bool:
    if item.get("kind") == "action":
        steps = [s for s in item.get("steps", []) if s.get("type") == "open"]
        return all(step_exists(s) for s in steps)
    return step_exists(item)


def is_local_target(item: dict) -> bool:
    t = expand(item.get("target", ""))
    return bool(t) and not is_url(t) and ("\\" in t or "/" in t)


def new_item(**kw) -> dict:
    d = {"id": new_id(), "name": "", "category": "apps", "kind": "open",
         "target": "", "args": "", "workdir": "", "steps": [],
         "last_used": 0, "added": now()}
    d.update(kw)
    return d


def read_url_file(p) -> str:
    try:
        for line in Path(p).read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().lower().startswith("url="):
                return line.strip()[4:]
    except OSError:
        pass
    return ""


def item_from_path(path: str) -> dict:
    p = Path(path)
    it = new_item(target=str(p))
    if p.is_dir():
        it["category"] = "folders"
        it["name"] = p.name or str(p)
        return it
    ext = p.suffix.lower()
    it["name"] = p.stem if ext in APP_EXT | {".url"} else p.name
    if ext == ".url":
        u = read_url_file(p)
        if u.lower().startswith(GAME_URL_PREFIXES):
            it["category"] = "games"
        elif is_web(u):
            it["category"], it["target"] = "links", u
        else:
            it["category"] = "apps"
    elif ext in APP_EXT:
        it["category"] = "apps"
    else:
        it["category"] = "files"
    return it


def item_from_url(u: str) -> dict:
    it = new_item(target=u)
    if u.lower().startswith(GAME_URL_PREFIXES):
        it["category"], it["name"] = "games", "Game"
    else:
        host = urlparse(u).netloc
        it["category"] = "links"
        it["name"] = host[4:] if host.startswith("www.") else (host or u)
    return it


def find_surfshark() -> str:
    for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if not base:
            continue
        for c in (Path(base) / "Surfshark" / "Surfshark.exe",
                  Path(base) / "Programs" / "Surfshark" / "Surfshark.exe"):
            if c.exists():
                return str(c)
    return ""


def surfshark_action(path: str) -> dict:
    return new_item(name="VPN ON (Surfshark)", category="actions", kind="action",
                    steps=[{"type": "open", "target": path, "args": ""}])


def fmt_date(ts: float) -> str:
    if not ts:
        return "never"
    d = datetime.fromtimestamp(ts)
    return d.strftime("%H:%M today") if d.date() == datetime.now().date() else d.strftime("%d %b")


def mono_font(px: int = 13, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(MONO_FAMILIES)
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPixelSize(px)
    f.setBold(bold)
    return f


# ============================================================ Windows integration
def launch_parts():
    """(executable, arguments) that start this app."""
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    return str(pyw if pyw.exists() else exe), f'"{Path(__file__).resolve()}"'


def set_autostart(enabled: bool) -> bool:
    if not IS_WIN:
        return False
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                             winreg.KEY_SET_VALUE)
        if enabled:
            exe, args = launch_parts()
            cmd = f'"{exe}" {args} --tray' if args else f'"{exe}" --tray'
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except OSError:
        return False


def create_desktop_shortcut():
    if not IS_WIN:
        return False, "Desktop shortcuts only work on Windows"
    exe, args = launch_parts()
    if getattr(sys, "frozen", False):
        icon, wd = exe, str(Path(exe).parent)
    else:
        icon, wd = str(resource_path("launchpad.ico")), str(Path(__file__).resolve().parent)

    def q(s):
        return str(s).replace("'", "''")

    ps = ("$s=New-Object -ComObject WScript.Shell;"
          "$d=[Environment]::GetFolderPath('Desktop');"
          "$l=$s.CreateShortcut((Join-Path $d 'Launchpad.lnk'));"
          f"$l.TargetPath='{q(exe)}';$l.Arguments='{q(args)}';"
          f"$l.WorkingDirectory='{q(wd)}';$l.IconLocation='{q(icon)}';"
          "$l.Description='Launchpad';$l.Save()")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                           capture_output=True, text=True, creationflags=0x08000000, timeout=30)
        if r.returncode == 0:
            return True, "Shortcut created on your desktop"
        return False, r.stderr.strip() or "PowerShell couldn't create the shortcut"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def style_titlebar(widget):
    """Black Windows 11 title bar with white caption text."""
    if not IS_WIN:
        return
    try:
        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi
        one = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(one), 4)        # dark mode
        black, white = ctypes.c_int(0x000000), ctypes.c_int(0xFFFFFF)
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(black), 4)      # caption colour
        dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(white), 4)      # caption text
        dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(ctypes.c_int(0x444444)), 4)  # border
    except Exception:  # noqa: BLE001
        pass


MODS = {"ctrl": 0x2, "control": 0x2, "alt": 0x1, "shift": 0x4, "meta": 0x8, "win": 0x8}
SPECIAL_VK = {"SPACE": 0x20, "TAB": 0x09, "RETURN": 0x0D, "ENTER": 0x0D, "HOME": 0x24,
              "END": 0x23, "INS": 0x2D, "DEL": 0x2E, "PGUP": 0x21, "PGDOWN": 0x22,
              "`": 0xC0, "/": 0xBF, ";": 0xBA, "'": 0xDE, "[": 0xDB, "]": 0xDD,
              "\\": 0xDC, ",": 0xBC, ".": 0xBE, "-": 0xBD, "=": 0xBB}


def parse_hotkey(text: str):
    parts = [p.strip() for p in (text or "").split("+") if p.strip()]
    mods, key = 0, None
    for p in parts:
        if p.lower() in MODS:
            mods |= MODS[p.lower()]
        else:
            key = p
    if not key or not mods:
        return None
    ku = key.upper()
    if len(ku) == 1 and ku.isalnum():
        vk = ord(ku)
    elif re.fullmatch(r"F([1-9]|1[0-9]|2[0-4])", ku):
        vk = 0x6F + int(ku[1:])
    else:
        vk = SPECIAL_VK.get(ku)
    return (mods, vk) if vk else None


class HotkeyManager(QObject):
    """System-wide hotkey via Win32 RegisterHotKey on a small message thread."""
    triggered = Signal()

    def __init__(self):
        super().__init__()
        self._tid = None
        self._thread = None

    def register(self, text: str):
        self.unregister()
        if not IS_WIN:
            return False, "Global hotkeys only work on Windows"
        parsed = parse_hotkey(text)
        if not parsed:
            return False, f"'{text}' won't work. Use Ctrl/Alt/Shift/Win plus a key."
        mods, vk = parsed
        ready, res = threading.Event(), {"ok": False}

        def run():
            from ctypes import wintypes
            user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
            self._tid = kernel32.GetCurrentThreadId()
            res["ok"] = bool(user32.RegisterHotKey(None, 1, mods | 0x4000, vk))
            ready.set()
            if not res["ok"]:
                return
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312:       # WM_HOTKEY
                    self.triggered.emit()
            user32.UnregisterHotKey(None, 1)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        ready.wait(2)
        if not res["ok"]:
            self._tid = None
            return False, f"{text} is already taken by another app. Pick another."
        return True, f"{text} is active"

    def unregister(self):
        if IS_WIN and self._tid:
            ctypes.windll.user32.PostThreadMessageW(self._tid, 0x0012, 0, 0)   # WM_QUIT
            if self._thread:
                self._thread.join(1)
        self._tid = None
        self._thread = None


# ============================================================ data
class Store:
    def __init__(self, path: Path):
        self.path = path
        self.data = self._load()

    @staticmethod
    def _default():
        return {"version": 1,
                "settings": {"hotkey": DEFAULT_HOTKEY, "start_with_windows": True,
                             "close_to_tray": True, "hide_after_launch": False,
                             "animation": True, "anim_speed": 1, "ascents": 0,
                             "first_run": True, "tray_tip_shown": False,
                             "art": "sisyphus", "art_small": "same", "banner_size": "medium",
                             "banner_hidden": False, "collapsed": []},
                "items": [], "projects": [], "pins": [], "tasks": [], "reminders": []}

    def _load(self):
        d = self._default()
        bak = self.path.with_suffix(".json.bak")
        for i, candidate in enumerate((self.path, bak)):
            if not candidate.exists():
                continue
            try:
                loaded = json.loads(candidate.read_text(encoding="utf-8"))
                d["settings"].update(loaded.get("settings", {}))
                d["items"] = list(loaded.get("items", []))
                d["projects"] = list(loaded.get("projects", []))
                d["pins"] = list(loaded.get("pins", []))
                d["tasks"] = list(loaded.get("tasks", []))
                d["reminders"] = list(loaded.get("reminders", []))
                if i == 0:
                    shutil.copy2(self.path, bak)
                break
            except (OSError, ValueError):
                continue
        return d

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    @property
    def settings(self):
        return self.data["settings"]

    # items
    def items(self, cat=None):
        return [i for i in self.data["items"] if cat is None or i.get("category") == cat]

    def get_item(self, iid):
        return next((i for i in self.data["items"] if i["id"] == iid), None)

    def add_item(self, item):
        self.data["items"].append(item)
        self.save()

    def update_item(self, item):
        for n, i in enumerate(self.data["items"]):
            if i["id"] == item["id"]:
                self.data["items"][n] = item
        self.save()

    def remove_item(self, iid):
        self.data["items"] = [i for i in self.data["items"] if i["id"] != iid]
        self.data["pins"] = [x for x in self.data.get("pins", []) if x != iid]
        self.save()

    def move_to(self, iid, cat, before_id=None):
        """Put an item in a section, optionally just before another item."""
        items = self.data["items"]
        it = self.get_item(iid)
        if not it:
            return
        if before_id == iid:
            it["category"] = cat
            self.save()
            return
        items.remove(it)
        it["category"] = cat
        before = self.get_item(before_id) if before_id else None
        if before is not None:
            idx = items.index(before)
        else:
            same = [n for n, i in enumerate(items) if i.get("category") == cat]
            idx = same[-1] + 1 if same else len(items)
        items.insert(idx, it)
        self.save()

    # pinned strip (independent of section)
    def pins(self):
        return [i for i in (self.get_item(x) for x in self.data.setdefault("pins", [])) if i]

    def is_pinned(self, iid):
        return iid in self.data.get("pins", [])

    def pin(self, iid, before_id=None):
        p = self.data.setdefault("pins", [])
        if iid in p:
            if before_id == iid:
                return
            p.remove(iid)
        if before_id in p:
            p.insert(p.index(before_id), iid)
        else:
            p.append(iid)
        self.save()

    def unpin(self, iid):
        self.data["pins"] = [x for x in self.data.get("pins", []) if x != iid]
        self.save()

    def move_item(self, iid, delta):
        items = self.data["items"]
        it = self.get_item(iid)
        if not it:
            return
        idx = [n for n, i in enumerate(items) if i.get("category") == it.get("category")]
        pos = next(k for k, n in enumerate(idx) if items[n]["id"] == iid)
        new = pos + delta
        if 0 <= new < len(idx):
            a, b = idx[pos], idx[new]
            items[a], items[b] = items[b], items[a]
            self.save()

    # to-do tasks
    def tasks(self):
        return self.data.setdefault("tasks", [])

    def get_task(self, tid):
        return next((t for t in self.tasks() if t["id"] == tid), None)

    def add_task(self, text, urgency=3, due=""):
        t = {"id": new_id(), "text": text, "urgency": int(urgency), "due": due, "notes": "",
             "done": False, "done_at": 0, "created": now()}
        self.tasks().append(t)
        self.save()
        return t

    def remove_task(self, tid):
        self.data["tasks"] = [t for t in self.tasks() if t["id"] != tid]
        self.save()

    # calendar reminders
    def reminders(self):
        return self.data.setdefault("reminders", [])

    def get_reminder(self, rid):
        return next((r for r in self.reminders() if r["id"] == rid), None)

    def add_reminder(self, day_iso, text, time_=""):
        r = {"id": new_id(), "date": day_iso, "text": text, "time": time_ or "", "created": now()}
        self.reminders().append(r)
        self.save()
        return r

    def remove_reminder(self, rid):
        self.data["reminders"] = [r for r in self.reminders() if r["id"] != rid]
        self.save()

    # projects
    def projects(self):
        return self.data["projects"]

    def get_project(self, pid):
        return next((p for p in self.data["projects"] if p["id"] == pid), None)

    def add_project(self, name):
        p = {"id": new_id(), "name": name, "status": "active", "notes": "",
             "todos": [], "items": [], "created": now(), "updated": now()}
        self.data["projects"].append(p)
        self.save()
        return p

    def remove_project(self, pid):
        self.data["projects"] = [p for p in self.data["projects"] if p["id"] != pid]
        self.save()


# ============================================================ launching
class Launcher(QObject):
    error = Signal(str)

    @staticmethod
    def open_target(target, args="", workdir=""):
        t = expand(target)
        if not t:
            raise ValueError("nothing to open")
        if IS_WIN:
            wd = expand(workdir) if workdir else ""
            if not wd and not is_url(t) and os.path.isfile(t) and args:
                wd = os.path.dirname(t)
            if args or wd:
                os.startfile(t, "open", args or "", wd or None)
            else:
                os.startfile(t)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", t])
        else:
            subprocess.Popen(["xdg-open", t], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def run(self, item):
        def work():
            if IS_WIN:
                try:
                    ctypes.windll.ole32.CoInitializeEx(None, 0x2 | 0x4)
                except Exception:  # noqa: BLE001
                    pass
            try:
                if item.get("kind") == "action":
                    for st in item.get("steps", []):
                        if st.get("type") == "wait":
                            time.sleep(max(0.0, float(st.get("seconds", 1))))
                        else:
                            self.open_target(st.get("target", ""), st.get("args", ""), st.get("workdir", ""))
                else:
                    self.open_target(item.get("target", ""), item.get("args", ""), item.get("workdir", ""))
            except Exception as e:  # noqa: BLE001
                self.error.emit(f"Couldn't open {item.get('name') or 'that'}: {e}")
        threading.Thread(target=work, daemon=True).start()


def open_location(target: str):
    t = expand(target)
    if IS_WIN:
        subprocess.Popen(f'explorer /select,"{t}"')
    else:
        subprocess.Popen(["xdg-open", str(Path(t).parent)])


# ============================================================ icons
_icon_cache: dict = {}
_provider = None


def glyph_pixmap(kind: str, size: int = 20, color: str = "#e6e6e6") -> QPixmap:
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.4)
    p.setPen(pen)
    s = float(size)
    if kind == "web":
        p.drawEllipse(QRectF(2.5, 2.5, s - 5, s - 5))
        p.drawEllipse(QRectF(s / 2 - 3.5, 2.5, 7, s - 5))
        p.drawLine(QPointF(2.5, s / 2), QPointF(s - 2.5, s / 2))
    elif kind == "play":
        p.setBrush(QColor(color))
        p.drawPolygon(QPolygonF([QPointF(6, 4), QPointF(6, s - 4), QPointF(s - 4, s / 2)]))
    elif kind == "action":
        p.drawPolyline(QPolygonF([QPointF(4, 5), QPointF(9, s / 2), QPointF(4, s - 5)]))
        p.drawLine(QPointF(11, s - 5), QPointF(s - 3, s - 5))
    elif kind == "project":
        p.drawRect(QRectF(4.5, 2.5, s - 9, s - 5))
        for y in (7, 10.5, 14):
            p.drawLine(QPointF(7, y), QPointF(s - 7, y))
    elif kind == "plus":
        p.drawLine(QPointF(s / 2, 4), QPointF(s / 2, s - 4))
        p.drawLine(QPointF(4, s / 2), QPointF(s - 4, s / 2))
    else:  # missing
        p.setFont(mono_font(15, True))
        p.drawText(QRectF(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, "?")
    p.end()
    return pm


def gray_pixmap(icon: QIcon, size: int = 20):
    pm = icon.pixmap(QSize(size, size))
    if pm.isNull():
        return None
    img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            g = min(255, int(0.3 * c.red() + 0.59 * c.green() + 0.11 * c.blue()) + 25)
            img.setPixelColor(x, y, QColor(g, g, g, c.alpha()))
    out = QPixmap.fromImage(img)
    out.setDevicePixelRatio(pm.devicePixelRatio())
    return out


def item_pixmap(item: dict, missing: bool = False) -> QPixmap:
    global _provider
    if missing:
        return glyph_pixmap("missing")
    if item.get("kind") == "action":
        return glyph_pixmap("action")
    t = expand(item.get("target", ""))
    if is_url(t):
        return glyph_pixmap("web" if is_web(t) else "play")
    if t in _icon_cache:
        return _icon_cache[t]
    if _provider is None:
        _provider = QFileIconProvider()
    pm = gray_pixmap(_provider.icon(QFileInfo(t))) or glyph_pixmap("action")
    _icon_cache[t] = pm
    return pm


# ============================================================ flow layout
class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self._items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, rect, test):
        x, y, line = rect.x(), rect.y(), 0
        sp = self.spacing()
        for it in self._items:
            w = it.widget()
            if w is not None and w.isHidden():
                continue
            hint = it.sizeHint()
            nx = x + hint.width() + sp
            if nx - sp > rect.right() + 1 and line > 0:
                x, y, line = rect.x(), y + line + sp, 0
                nx = x + hint.width() + sp
            if not test:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x = nx
            line = max(line, hint.height())
        return y + line - rect.y()


# ============================================================ ASCII art
LANDMASK_B64 = "eNqtk79v1DAUx5/j6AKiIpUAqUPBN7LRkQFdIv4Nht5/AOMNqDGqVHVAiP8A/gQGBraGiQUBA0NHb0XqUCNdIUPOj/dsx017C0JYyt3LJ++Xv88G+Nf1YInOAGQJyOorIhSazNYDceNdicjvJuuCS/seKiRjAtUP0KBreP7UVo5IfhfxdwcS8fuThSLD3TlFXpYeN1NtLVeVBwj0nG8r0KoJACkK2/kEYBaI+wDzBs0e5Z2FIN2SO3ZUKbsdXKTOoURH/V1XMQu5F5wJRMzre0Zc1pcI2Sv6w3OfRwcfS/zUMOnrQEic4uCX34IOUSRLmb3hoOkFAcs18ZYXqOECheX9YO7JLotT9l4L7Un1kQniWSLlC8a4+hkbhDAFIk6FBqmhQ5/eYXli4ryOt9jHueLTtzjChWAfXBTChCi46aPQSGHb6HTfk9cSntUBiAZAsQIinYVGQ3lEROtELDsZEAcDYclKVuBVIksmGsSXlwOht5L39Hi/HUhLQyJjKswVkr2N1RqKkl6JazEPH7oCN8naiER5skPWXtwG1ykck8aMSD/ladpIenrp5xzaRUJfZOcnHonio3CZUD5h1whXkfsDSUpBrKVGly3cskcXYJr7rrdHPmGvD0dkc42EtbNGtuA/LX0VhM5J9c+D8hP+yZEPax/IPX5HPOEzTqLk4I54ZHEZvkwkXDEAmi59dIcbzYg03icBTDc2rQ7/Yv0B7Y6suA=="
LAND_W, LAND_H = 144, 72


def _blank(W, H):
    return [[" "] * W for _ in range(H)]


def _blit(grid, sprite, left, top, opaque):
    H, W = len(grid), len(grid[0])
    for r, line in enumerate(sprite):
        y = top + r
        if not 0 <= y < H:
            continue
        first = len(line) - len(line.lstrip())
        last = len(line.rstrip())
        for c, ch in enumerate(line):
            x = left + c
            if not 0 <= x < W:
                continue
            if ch == "`" and opaque:
                grid[y][x] = " "          # explicit see-through-nothing padding
            elif ch != " ":
                grid[y][x] = ch
            elif opaque and first <= c < last:
                grid[y][x] = " "


class Stars:
    """Twinkling starfield shared by the space arts."""

    def __init__(self, W, H, n, seed):
        rnd = random.Random(seed)
        self.stars = [(rnd.randrange(W), rnd.randrange(H), rnd.randrange(40)) for _ in range(n)]

    def draw(self, g, t):
        for x, y, ph in self.stars:
            k = (t + ph) % 40
            g[y][x] = "*" if k == 0 else "+" if k in (1, 39) else "."


# ============================================================ Sisyphus
class SisyphusScene:
    BOULDER = [
        "   .--.   ",
        " .'    '. ",
        "|        |",
        " '.    .' ",
        "   '--'   ",
    ]
    RING = [(1, 4), (1, 5), (2, 7), (3, 5), (3, 4), (2, 2)]
    PUSH = [
        ["     o ",
         "    /==",
         "   /   ",
         "  / \\  ",
         " /   \\ "],
        ["     o ",
         "    /==",
         "   /   ",
         "  /|   ",
         " / |   "],
    ]
    STAND = ["       ",
             "   o   ",
             "  /|\\  ",
             "   |   ",
             "  / \\  "]
    WALK = [STAND,
            ["       ",
             "   o   ",
             "  /|\\  ",
             "   |   ",
             "   |   "]]
    CLOUD = ["   .--.    ",
             " .(    )-. ",
             "(___.__)__)"]

    def __init__(self, counter=None, compact=False):
        self.counter = counter if counter is not None else {"n": 0}
        self.compact = compact
        if compact:
            self.W, self.H, self.rise, self.run = 110, 10, 3, 22
            self.clouds = [[30.0, 0]]
        else:
            self.W, self.H, self.rise, self.run = 100, 18, 11, 6
            self.clouds = [[6.0, 0], [57.0, 1]]
        self.BASE = self.H - 1
        self.START, self.PEAK = 14, 71
        self.ground = self._terrain()
        self._reset()

    @property
    def ascents(self):
        return self.counter["n"]

    def captions(self):
        return f"ASCENT {self.ascents:04d}", "ONE MUST IMAGINE SISYPHUS HAPPY"

    def _reset(self):
        self.phase, self.bx, self.fx = "push", self.START, self.START - 12
        self.rot = self.step = self.wait = 0

    def _terrain(self):
        g, top = [], self.BASE - self.rise
        for x in range(self.W):
            if x < 6:
                lv = self.BASE
            elif x <= 72:
                lv = self.BASE - min(self.rise, (x - 6) // self.run)
            elif x <= 80:
                lv = top
            else:
                lv = min(self.BASE, top + (x - 80 + 1) // 2)
            g.append(lv)
        return g

    def ground_at(self, x):
        return self.ground[max(0, min(self.W - 1, x))]

    def tick(self):
        for c in self.clouds:
            c[0] += 1 / 7
            if c[0] > self.W:
                c[0] = -len(self.CLOUD[2])
        p = self.phase
        if p == "push":
            self.step += 1
            if self.step % 2 == 0:
                self.bx += 1
                self.fx += 1
                self.rot = (self.rot + 1) % 6
                if self.bx >= self.PEAK:
                    self.phase, self.wait = "teeter", 0
                    self.counter["n"] += 1
        elif p == "teeter":
            self.wait += 1
            if self.wait > 16:
                self.phase, self.step = "roll", 0
        elif p == "roll":
            self.step += 1
            self.bx -= 2
            self.rot = (self.rot - 2) % 6
            if self.bx <= self.START:
                self.bx, self.phase, self.step = self.START, "walk", 0
        elif p == "walk":
            self.step += 1
            self.fx -= 1
            if self.fx <= self.START - 12:
                self.fx, self.phase, self.wait = self.START - 12, "rest", 0
        elif p == "rest":
            self.wait += 1
            if self.wait > 10:
                self.phase, self.step = "push", 0

    def render(self):
        W, H = self.W, self.H
        g = _blank(W, H)
        for cx, cy in self.clouds:
            _blit(g, self.CLOUD, int(cx), cy, True)
        for x in range(W):
            lv = self.ground[x]
            prev = self.ground[x - 1] if x else lv
            if lv < prev:
                g[prev][x] = "/"
                fill = prev + 1
            elif lv > prev:
                g[lv][x] = "\\"
                fill = lv + 1
            else:
                g[lv][x] = "_"
                fill = lv + 1
            for y in range(fill, H):
                if (x * 3 + y * 7) % 13 == 0:
                    g[y][x] = "."
                elif (x * 5 + y * 11) % 29 == 0:
                    g[y][x] = "'"
        if self.phase == "push":
            fig = self.PUSH[(self.step // 4) % 2]
        elif self.phase in ("teeter", "rest"):
            fig = self.PUSH[0]
        elif self.phase == "roll":
            fig = self.STAND
        else:
            fig = self.WALK[(self.step // 3) % 2]
        fx = int(self.fx)
        _blit(g, fig, fx, self.ground_at(fx + 3) - 4, False)
        c = self.bx
        if self.phase == "teeter":
            c += 1 if (self.wait // 2) % 2 else 0
        gy = self.ground_at(c)
        if self.phase == "roll" and self.step % 6 in (2, 3):
            gy -= 1
        b = [list(row) for row in self.BOULDER]
        for k, ch in ((0, "."), (3, ":")):
            r, col = self.RING[(self.rot + k) % 6]
            b[r][col] = ch
        _blit(g, ["".join(row) for row in b], c - 5, gy - 4, True)
        return ["".join(row) for row in g]


# ============================================================ Globe
class Globe:
    W, H = 100, 18
    LAND = " .:-=+*#%@"
    TILT = math.radians(23.4)

    def __init__(self, *_):
        bits = zlib.decompress(base64.b64decode(LANDMASK_B64))
        flat = []
        for byte in bits:
            for k in range(7, -1, -1):
                flat.append((byte >> k) & 1)
        self.land = [flat[r * LAND_W:(r + 1) * LAND_W] for r in range(LAND_H)]
        self.lon0 = 0.0
        self.t = 0
        self.stars = Stars(self.W, self.H, 34, 7)
        l = (-0.55, 0.35, 0.76)
        n = math.sqrt(sum(v * v for v in l))
        self.light = tuple(v / n for v in l)

    def captions(self):
        deg = int(math.degrees(self.lon0)) % 360
        return "EARTH", f"LON {deg:03d}"

    def tick(self):
        self.t += 1
        self.lon0 = (self.lon0 + math.radians(2.0)) % (2 * math.pi)

    def render(self):
        W, H = self.W, self.H
        g = _blank(W, H)
        self.stars.draw(g, self.t)
        cy, cx = H / 2, W / 2
        ry = H / 2 - 0.4
        rx = ry * 2.1
        ct, st = math.cos(self.TILT), math.sin(self.TILT)
        lx, ly, lz = self.light
        for y in range(H):
            ny = -((y + 0.5) - cy) / ry
            for x in range(W):
                nx = ((x + 0.5) - cx) / rx
                r2 = nx * nx + ny * ny
                if r2 > 1.0:
                    continue
                nz = math.sqrt(1.0 - r2)
                # undo axial tilt (rotate about view z), then lat/lon
                wx = nx * ct + ny * st
                wy = -nx * st + ny * ct
                lat = math.asin(max(-1.0, min(1.0, wy)))
                lon = math.atan2(wx, nz) + self.lon0
                col = int(((lon / (2 * math.pi)) % 1.0) * LAND_W) % LAND_W
                row = min(LAND_H - 1, int((0.5 - lat / math.pi) * LAND_H))
                b = max(0.0, nx * lx + ny * ly + nz * lz)
                if self.land[row][col]:
                    g[y][x] = self.LAND[max(2, min(9, int(2 + b * 8)))]
                else:
                    if r2 > 0.9:
                        g[y][x] = "."            # limb, so the globe's outline always shows
                    elif b > 0.3 and (row * 31 + col * 17) % 11 == 0:
                        g[y][x] = "~" if b > 0.7 else "."   # sea texture turns with the globe
                    else:
                        g[y][x] = " "
        return ["".join(r) for r in g]


# ============================================================ Saturn
class Saturn:
    W, H = 100, 18
    RAMP = " .:-=+*#%@"

    def __init__(self, *_):
        self.t = 0
        self.stars = Stars(self.W, self.H, 30, 11)
        l = (-0.6, 0.45, 0.66)
        n = math.sqrt(sum(v * v for v in l))
        self.light = tuple(v / n for v in l)

    def tilt(self):
        return math.radians(20 + 8 * math.sin(self.t * 2 * math.pi / 600))

    def captions(self):
        return "SATURN", f"RING TILT {math.degrees(self.tilt()):4.1f}"

    def tick(self):
        self.t += 1

    def render(self):
        W, H = self.W, self.H
        g = _blank(W, H)
        self.stars.draw(g, self.t)
        cy, cx = H / 2, W / 2
        ry = 5.6
        rx = ry * 2.1
        phi = self.tilt()
        cp, sp = math.cos(phi), math.sin(phi)
        lx, ly, lz = self.light
        spin = self.t * 0.09
        for y in range(H):
            Y = -((y + 0.5) - cy) / ry
            for x in range(W):
                X = ((x + 0.5) - cx) / rx
                ch = None
                # ring plane: normal (0, cp, sp) through origin
                tr = -Y * cp / sp
                rr = math.sqrt(X * X + Y * Y + tr * tr)
                ring = 1.22 <= rr <= 2.3 and not (1.88 <= rr <= 1.96)
                d2 = X * X + Y * Y
                ts = math.sqrt(1 - d2) if d2 <= 1 else None
                if ring and (ts is None or tr > ts):
                    # in-plane angle for moving particle texture
                    ang = math.atan2(tr, X) + spin / max(rr, 1.0) ** 1.5
                    clump = math.sin(ang * 9 + rr * 7) > 0.65
                    if rr < 1.5:
                        ch = "." if clump or (x + y) % 2 else " "
                    elif rr < 1.88:
                        ch = "#" if clump else "="
                    else:
                        ch = "=" if clump else "-"
                    # planet shadow falls on the ring behind it
                    if tr < 0 and d2 <= 1.0:
                        ch = " "
                elif ts is not None:
                    # planet: latitude measured against the ring normal
                    lat = Y * cp + ts * sp
                    b = max(0.0, X * lx + Y * ly + ts * lz)
                    band = math.sin(lat * 13.0)
                    lvl = b * 7 + (1.2 if band > 0.35 else 0) - (0.8 if band < -0.6 else 0)
                    # a storm that rotates with the planet
                    lon = math.atan2(X, ts * cp - Y * sp) + spin
                    if abs(lat + 0.35) < 0.08 and math.cos(lon) > 0.93:
                        lvl -= 3
                    ch = self.RAMP[max(1, min(9, int(lvl) + 1))]
                if ch:
                    g[y][x] = ch
        return ["".join(r) for r in g]


# ============================================================ Storm
class Storm:
    W, H = 100, 18
    CLOUD = " .:;oO@"

    def __init__(self, *_):
        self.rnd = random.Random(3)
        self.t = 0
        self.drops = []
        self.splashes = []
        self.bolt = None
        self.bolt_life = 0
        self.next_bolt = 30
        self.strikes = 0
        self.blobs = [[self.rnd.uniform(0, self.W), self.rnd.uniform(0.5, 3.0),
                       self.rnd.uniform(6, 13), self.rnd.uniform(1.6, 2.6), self.rnd.uniform(0.04, 0.09)]
                      for _ in range(13)]
        self.ground = self.H - 1

    def captions(self):
        return "STORM", f"STRIKES {self.strikes:03d}"

    def _density(self, x, y):
        d = 0.0
        for bx, by, rx, ry, _ in self.blobs:
            dx = (x - bx) / rx
            if dx > 1.6 or dx < -1.6:
                dx2 = (x - bx + self.W + 16) / rx if x < bx else (x - bx - self.W - 16) / rx
                dx = dx2 if abs(dx2) < abs(dx) else dx
            dy = (y - by) / ry
            v = 1 - (dx * dx + dy * dy)
            if v > 0:
                d += v
        return d

    def tick(self):
        self.t += 1
        for b in self.blobs:
            b[0] += b[4]
            if b[0] > self.W + 14:
                b[0] = -14
        for _ in range(14):
            x = self.rnd.uniform(-6, self.W)
            if self._density(x, 3.5) > 0.15:
                self.drops.append([x, 5.0, self.rnd.uniform(0.9, 1.4)])
        nd = []
        for d in self.drops:
            d[1] += d[2]
            d[0] += d[2] * 0.45
            if d[1] >= self.ground:
                if 0 <= int(d[0]) < self.W:
                    self.splashes.append([int(d[0]), 3])
            else:
                nd.append(d)
        self.drops = nd
        self.splashes = [[x, l - 1] for x, l in self.splashes if l > 1]
        if self.bolt_life:
            self.bolt_life -= 1
            if not self.bolt_life:
                self.bolt = None
        self.next_bolt -= 1
        if self.next_bolt <= 0:
            self._make_bolt()
            self.next_bolt = self.rnd.randint(35, 90)

    def _make_bolt(self):
        x = self.rnd.randint(18, self.W - 18)
        path = []
        branch = None
        y = 5
        while y < self.ground:
            step = self.rnd.choice((-1, 0, 1, 1, -1))
            ch = "|" if step == 0 else ("\\" if step > 0 else "/")
            path.append((x, y, ch))
            if branch is None and y > 7 and self.rnd.random() < 0.25:
                branch = (x, y)
            x = max(1, min(self.W - 2, x + step))
            y += 1
        if branch:
            bx, by = branch
            d = self.rnd.choice((-1, 1))
            for k in range(1, self.rnd.randint(3, 5)):
                path.append((bx + d * k, by + k, "\\" if d > 0 else "/"))
        path.append((x, self.ground, "*"))
        self.bolt = path
        self.bolt_life = 4
        self.strikes += 1

    def render(self):
        W, H = self.W, self.H
        g = _blank(W, H)
        flash = self.bolt is not None and self.bolt_life in (4, 2)
        for y in range(0, 6):
            for x in range(W):
                d = self._density(x + 0.5, y + 0.5)
                if d > 0.12:
                    k = int(min(1.0, d / 1.4) * (len(self.CLOUD) - 1)) + (1 if flash else 0)
                    g[y][x] = self.CLOUD[max(1, min(len(self.CLOUD) - 1, k))]
        for x, y, _ in self.drops:
            xi, yi = int(x), int(y)
            if 0 <= xi < W and 5 <= yi < self.ground:
                g[yi][xi] = "\\" if (xi + yi) % 3 else "`"
        for x in range(W):
            g[self.ground][x] = "~" if (x * 7 + self.t // 6) % 23 == 0 else "_"
        for x, life in self.splashes:
            if 0 <= x < W:
                g[self.ground - 1][x] = "o" if life == 2 else "."
        if self.bolt and self.bolt_life != 3:
            for x, y, ch in self.bolt:
                if 0 <= x < W and 0 <= y < H:
                    g[y][x] = ch
        return ["".join(r) for r in g]


# ============================================================ custom .txt art
class CustomArt:
    """Frames from a .txt file. Frames are separated by a line reading ---frame---
    An optional first line 'fps 8' sets the speed (default 8)."""

    def __init__(self, path):
        from pathlib import Path
        self.name = Path(path).stem
        text = Path(path).read_text(encoding="utf-8", errors="replace").replace("\t", "    ")
        lines = text.splitlines()
        self.fps = 8.0
        if lines and lines[0].lower().startswith("fps"):
            try:
                self.fps = max(0.5, min(30.0, float(lines[0].split()[1])))
            except (IndexError, ValueError):
                pass
            lines = lines[1:]
        frames, cur = [], []
        for ln in lines:
            if ln.strip().lower() == "---frame---":
                frames.append(cur)
                cur = []
            else:
                cur.append(ln.rstrip())
        frames.append(cur)
        frames = [f for f in frames if any(l.strip() for l in f)] or [["(empty art file)"]]
        self.H = max(len(f) for f in frames)
        self.W = max(1, max(len(l) for f in frames for l in f))
        self.frames = [[l.ljust(self.W) for l in f] + [" " * self.W] * (self.H - len(f)) for f in frames]
        self.t = 0.0

    def captions(self):
        return self.name.upper(), ""

    def tick(self, dt=0.1):
        self.t += dt

    def render(self):
        return self.frames[int(self.t * self.fps) % len(self.frames)]


# ============================================================ bitmap font (5x7)
FONT5x7 = {
    "L": ["#....", "#....", "#....", "#....", "#....", "#....", "#####"],
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "U": ["#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "N": ["#...#", "##..#", "#.#.#", "#.#.#", "#..##", "#...#", "#...#"],
    "C": [".####", "#....", "#....", "#....", "#....", "#....", ".####"],
    "H": ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "P": ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
    "D": ["####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."],
    "0": [".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."],
    "1": ["..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "2": [".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"],
    "3": ["####.", "....#", "....#", ".###.", "....#", "....#", "####."],
    "4": ["...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."],
    "5": ["#####", "#....", "####.", "....#", "....#", "#...#", ".###."],
    "6": [".###.", "#....", "#....", "####.", "#...#", "#...#", ".###."],
    "7": ["#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."],
    "8": [".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."],
    "9": [".###.", "#...#", "#...#", ".####", "....#", "....#", ".###."],
}


def text_mask(text, sx=2, sy=1, gap=1):
    """Boolean grid for text in the 5x7 font, scaled sx by sy."""
    cols = []
    for n, ch in enumerate(text):
        g = FONT5x7.get(ch)
        if g is None:
            cols.extend([[False] * (7 * sy)] * (3 * sx))
            continue
        for c in range(5):
            col = []
            for r in range(7):
                col.extend([g[r][c] == "#"] * sy)
            cols.extend([col] * sx)
        if n < len(text) - 1:
            cols.extend([[False] * (7 * sy)] * gap)
    h = 7 * sy
    return [[cols[x][y] for x in range(len(cols))] for y in range(h)]


# ============================================================ LAUNCHPAD title
class Title:
    W, H = 102, 18
    TEX = "%#%@#%"

    def __init__(self, *_):
        m = text_mask("LAUNCHPAD", sx=2, sy=2, gap=1)
        self.mh, self.mw = len(m), len(m[0])
        self.ox, self.oy = (self.W - self.mw) // 2, 2
        self.fill = set()
        for y in range(self.mh):
            for x in range(self.mw):
                if m[y][x]:
                    self.fill.add((x + self.ox, y + self.oy))
        self.edge = {}
        for x in range(self.W):
            for y in range(self.H):
                if (x, y) in self.fill:
                    continue
                n, s = (x, y - 1) in self.fill, (x, y + 1) in self.fill
                w, e = (x - 1, y) in self.fill, (x + 1, y) in self.fill
                diag = [(x + dx, y + dy) in self.fill for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1))]
                if s and not (w or e):
                    ch = "_"
                elif n and not (w or e):
                    ch = "-"
                elif w or e:
                    ch = "|"
                elif diag[2] or diag[3]:
                    ch = "."        # above a corner
                elif diag[0] or diag[1]:
                    ch = "'"        # below a corner
                else:
                    continue
                self.edge[(x, y)] = ch
        self.path = self._chain()
        self.t = 0
        self.phase, self.k = "trace", 0

    def _chain(self):
        left = set(self.edge)
        path = []
        while left:
            cur = min(left, key=lambda p: (p[0], p[1]))
            while cur:
                path.append(cur)
                left.discard(cur)
                x, y = cur
                nxt = None
                for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)):
                    if (x + dx, y + dy) in left:
                        nxt = (x + dx, y + dy)
                        break
                cur = nxt
        return path

    def captions(self):
        return "", "KEEP IT IN SIGHT"

    def tick(self):
        self.t += 1
        n = len(self.path)
        if self.phase == "trace":
            self.k += 7
            if self.k >= n:
                self.phase, self.k = "comet", 0
        elif self.phase == "comet":
            self.k += 5
            if self.k >= n * 2:
                self.phase, self.k = "hold", 0
        elif self.phase == "hold":
            self.k += 1
            if self.k > 30:
                self.phase, self.k = "trace", 0

    def render(self):
        g = [[" "] * self.W for _ in range(self.H)]
        band = (self.t * 1.6) % (self.W + 40) - 20
        for x, y in self.fill:
            d = x - y * 0.6 - band
            if -2.5 < d < 2.5:
                g[y][x] = "@" if abs(d) < 1.2 else "#"
            else:
                g[y][x] = "%" if (x + y) % 3 else ("#" if (x // 2 + y) % 2 else "%")
                if (x * 7 + y * 3) % 11 == 0:
                    g[y][x] = "&"
        n = len(self.path)
        if self.phase == "trace":
            upto = min(self.k, n)
            for i in range(upto):
                x, y = self.path[i]
                g[y][x] = self.edge[(x, y)]
            for j, ch in enumerate("@*+"):
                i = upto - j
                if 0 <= i < n:
                    x, y = self.path[i]
                    g[y][x] = ch
        else:
            for (x, y), ch in self.edge.items():
                g[y][x] = ch
            if self.phase == "comet":
                for j, ch in enumerate("@@*+:."):
                    i = (self.k - j) % n
                    x, y = self.path[i]
                    g[y][x] = ch
        return ["".join(r) for r in g]


# ============================================================ campsite
class Campsite:
    W, H = 100, 18
    GROUND = 15
    TREE = [
        "      /\\      ",
        "     /  \\     ",
        "    /    \\    ",
        "   /_    _\\   ",
        "    /    \\    ",
        "   /      \\   ",
        "  /_      _\\  ",
        "   /      \\   ",
        "  /        \\  ",
        " /_        _\\ ",
        "  /        \\  ",
        " /          \\ ",
        "/____________\\",
        "      ||      ",
        "      ||      ",
    ]
    SMALL_TREE = [
        "    /\\    ",
        "   /  \\   ",
        "  /_  _\\  ",
        "   /  \\   ",
        "  /    \\  ",
        " /_    _\\ ",
        "  /    \\  ",
        " /      \\ ",
        "/________\\",
        "    ||    ",
    ]
    TENT = [
        "      /\\      ",
        "     /  \\     ",
        "    / /\\ \\    ",
        "   / /  \\ \\   ",
        "  / /    \\ \\  ",
        " /_/______\\_\\ ",
    ]
    MOON = [
        "  _.._ ",
        ".' .-'`",
        "|  (   ",
        "'. '-._",
        "  `''` ",
    ]
    FLAMES = [
        ["   (   ",
         "  ) )  ",
         " ( ( ) ",
         "  ) )( "],
        ["    )  ",
         "   ( ( ",
         "  ) ) )",
         " ( ( ( "],
        ["  (    ",
         "   ) ) ",
         "  ( (( ",
         " ) )() "],
    ]
    LOGS = "_\\/\\/\\/_"
    SEAT = "[=====]"

    def __init__(self, *_):
        import random
        self.rnd = random.Random(5)
        self.t = 0
        self.sparks = []
        self.stars = [(self.rnd.randrange(self.W), self.rnd.randrange(9), self.rnd.randrange(40)) for _ in range(32)]
        self.fire_x = 62

    def captions(self):
        return "CAMPSITE", ""

    def tick(self):
        self.t += 1
        if self.rnd.random() < 0.35:
            self.sparks.append([self.fire_x + 2 + self.rnd.uniform(0, 3), self.GROUND - 5, self.rnd.randint(5, 10)])
        ns = []
        for s in self.sparks:
            s[0] += self.rnd.uniform(-0.6, 0.6)
            s[1] -= 0.6
            s[2] -= 1
            if s[2] > 0 and s[1] > 0:
                ns.append(s)
        self.sparks = ns

    def render(self):
        from_ = _blank(self.W, self.H)
        g = from_
        for x, y, ph in self.stars:
            k = (self.t + ph) % 40
            g[y][x] = "*" if k == 0 else "+" if k in (1, 39) else "."
        _blit(g, self.MOON, 88, 1, True)
        gy = self.GROUND
        for x in range(self.W):
            g[gy][x] = "_"
        for y in (gy + 1, gy + 2):
            for x in range(self.W):
                if (x * 5 + y * 3) % 17 == 0:
                    g[y][x] = ","
                elif (x * 3 + y * 11) % 23 == 0:
                    g[y][x] = "'"
        _blit(g, self.TREE, 3, gy - len(self.TREE) + 1, True)
        _blit(g, self.SMALL_TREE, 18, gy - len(self.SMALL_TREE) + 1, True)
        _blit(g, self.TENT, 34, gy - len(self.TENT), True)
        _blit(g, self.SMALL_TREE, 87, gy - len(self.SMALL_TREE) + 1, True)
        # fire, logs, stones, a seat
        fx = self.fire_x
        _blit(g, self.FLAMES[(self.t // 2) % 3], fx, gy - 5, False)
        _blit(g, [self.LOGS], fx - 1, gy - 1, False)
        for dx, ch in ((-3, "o"), (-2, "O"), (8, "O"), (9, "o")):
            g[gy][fx + dx] = ch
        _blit(g, [self.SEAT], fx + 12, gy - 1, False)
        g[gy][fx + 13] = "|"
        g[gy][fx + 17] = "|"
        for x, y, life in self.sparks:
            xi, yi = int(x), int(y)
            if 0 <= xi < self.W and 0 <= yi < self.H and g[yi][xi] == " ":
                g[yi][xi] = "*" if life > 7 else "." if life > 3 else "'"
        return ["".join(r) for r in g]


# ============================================================ fisherman
class Fisherman:
    W, H = 100, 18
    WATER = 10      # first water row
    DOCK = 12       # dock plank row
    MAN = [
        "     ___      ",
        "   _|___|_    ",
        "    (-.- )    ",
        "   ``)ww(``   ",
        "  `_/ || \\__/",
        "  /__|__|__\\ ",
    ]
    LEGS = ["     | |  ",
            "    _| |_ "]
    SUN = [
        "   .-''-.   ",
        " .'      '. ",
    ]
    REEDS = [")", "(", "|", ")", "|"]

    def __init__(self, *_):
        import random
        self.rnd = random.Random(9)
        self.t = 0
        self.nibbles = 0
        self.dip = 0
        self.next_nibble = 90
        self.fish = None
        self.next_fish = 60
        self.birds = [[70.0, 2], [76.0, 3], [82.0, 1]]
        self.man_x = 18
        self.tip = (2, 60)
        self.bob_x = 70

    def captions(self):
        return "THE LAKE", f"NIBBLES {self.nibbles:02d}"

    def tick(self):
        self.t += 1
        for b in self.birds:
            b[0] -= 0.25
            if b[0] < -3:
                b[0] = self.W + self.rnd.randint(0, 30)
        if self.dip:
            self.dip -= 1
        self.next_nibble -= 1
        if self.next_nibble <= 0:
            self.dip = 10
            self.nibbles += 1
            self.next_nibble = self.rnd.randint(120, 300)
        if self.fish:
            self.fish["k"] += 1
            if self.fish["k"] > 14:
                self.fish = None
        self.next_fish -= 1
        if self.next_fish <= 0:
            self.fish = {"x": self.rnd.randint(40, 92), "dir": self.rnd.choice((-1, 1)), "k": 0}
            self.next_fish = self.rnd.randint(80, 200)

    def render(self):
        W, H, wy = self.W, self.H, self.WATER
        g = _blank(W, H)
        # sky: birds
        for bx, by in self.birds:
            x = int(bx)
            if 0 <= x < W - 2:
                wing = "v" if (self.t // 4 + x) % 2 else "-"
                g[by][x] = wing
        # far hills and sun on the horizon
        hills = "   _/\\__        __/\\/\\___          __/\\______"
        for i, ch in enumerate(hills):
            if ch != " " and 44 + i < W:
                g[wy - 2 if ch in "/\\" else wy - 1][44 + i] = ch
        for x in range(W):
            g[wy - 1][x] = "_" if g[wy - 1][x] == " " else g[wy - 1][x]
        _blit(g, self.SUN, 80, wy - 3, True)
        # water texture and sun reflection
        for y in range(wy, H):
            for x in range(W):
                k = (x + (self.t // 3) * (1 if y % 2 else -1) + y * 7) % 19
                if k == 0:
                    g[y][x] = "~"
                elif k == 9 and (x + y) % 2:
                    g[y][x] = "-"
            for x in range(83, 90):
                if (x + y + self.t // 2) % 3 == 0 and y < wy + 5:
                    g[y][x] = "="
        # shore with grass at left
        for y in range(wy - 1, H):
            for x in range(0, 9 - (y - wy + 1) // 3):
                g[y][x] = "." if (x + y) % 4 == 0 else " "
        for x in range(0, 8):
            g[wy - 1][x] = "_"
        for i, x in enumerate((1, 3, 4, 6)):
            g[wy - 2][x] = "\\" if (self.t // 6 + i) % 2 else "|"
            g[wy - 3][x] = "/" if i % 2 else " "
        # dock
        for x in range(6, 38):
            g[self.DOCK][x] = "="
        for x in (8, 20, 34):
            for y in range(self.DOCK + 1, H):
                g[y][x] = "|"
        # reeds near the dock
        for i, x in enumerate((40, 42, 43)):
            for y in range(wy - 1, wy + 2):
                g[y][x] = self.REEDS[(i + y + self.t // 8) % len(self.REEDS)]
        # fisherman
        mx = self.man_x
        _blit(g, self.MAN, mx, self.DOCK - len(self.MAN), True)
        _blit(g, self.LEGS, mx + 2, self.DOCK + 1, True)
        # rod from his hands to the tip
        hy, hx = self.DOCK - 2, mx + 13
        ty, tx = self.tip
        bend = 1 if self.dip else 0
        pts = []
        steps = tx - hx
        for i in range(1, steps + 1):
            f = i / steps
            x = hx + i
            y = int(round(hy - (hy - ty - bend) * (1 - (1 - f) ** 2)))
            if pts:
                y = min(y, pts[-1][1])
            pts.append((x, y))
        prev = (hx, hy)
        for x, y in pts:
            ch = "/" if y < prev[1] else "_"
            if 0 <= y < H:
                g[y][x] = ch
            prev = (x, y)
        tip_x, tip_y = pts[-1]
        # line down to the bobber
        by = self.DOCK + 1 + (1 if self.dip else 0)
        bob_x = self.bob_x
        for y in range(tip_y + 1, by):
            f = (y - tip_y) / max(1, by - tip_y)
            x = int(round(tip_x + (bob_x - tip_x) * f))
            if g[y][x] in " ~-=":
                g[y][x] = ":" if y < wy else "|"
        if self.dip:
            ring = (10 - self.dip) // 2
            if ring:
                for dx in (-ring, ring):
                    if 0 <= bob_x + dx < W:
                        g[by][bob_x + dx] = "(" if dx < 0 else ")"
            g[by][bob_x] = "." if self.dip > 5 else "o"
        else:
            g[by][bob_x] = "o" if (self.t // 5) % 3 else "O"
        # jumping fish
        if self.fish:
            k, x0, d = self.fish["k"], self.fish["x"], self.fish["dir"]
            x = x0 + d * k
            y = wy + 1 - int(3 * math.sin(math.pi * k / 14))
            body = "><>" if d > 0 else "<><"
            if 0 < k < 14:
                for i, ch in enumerate(body):
                    if 0 <= x + i < W and 0 <= y < H:
                        g[y][x + i] = ch
            if k in (0, 1, 13, 14):
                sx = x0 if k < 2 else x0 + d * 14
                for dx, ch in ((-1, "."), (0, "o"), (1, ".")):
                    if 0 <= sx + dx < W:
                        g[wy][sx + dx] = ch
        return ["".join(r) for r in g]


# ============================================================ clock
class Clock:
    W, H = 56, 11
    live = True      # keeps ticking even if animation is paused

    def __init__(self, *_):
        pass

    def captions(self):
        return "", ""

    def tick(self):
        pass

    def render(self):
        from datetime import datetime as _dt
        now = _dt.now()
        g = _blank(self.W, self.H)

        def center(row, text):
            x0 = (self.W - len(text)) // 2
            for i, ch in enumerate(text):
                g[row][x0 + i] = ch
        center(0, now.strftime("%A").upper())
        hh, mm = now.strftime("%H"), now.strftime("%M")
        digits = [text_mask(c, sx=2, sy=1, gap=0) for c in hh + mm]
        colon_w = 6
        total = 4 * 10 + 2 * 2 + colon_w
        x = (self.W - total) // 2
        positions = []
        for i, dmask in enumerate(digits):
            positions.append(x)
            x += 10 + (2 if i != 1 else 0)
            if i == 1:
                colon_x = x
                x += colon_w
        for dmask, px in zip(digits, positions):
            for r in range(7):
                for c in range(10):
                    if dmask[r][c]:
                        g[2 + r][px + c] = "#"
        if now.second % 2 == 0:
            for r in (2 + 2, 2 + 4):
                g[r][colon_x + 2] = "#"
                g[r][colon_x + 3] = "#"
        center(10, now.strftime("%B %Y").upper())
        return ["".join(r) for r in g]


BUILTIN_ARTS = [("sisyphus", "Sisyphus"), ("sisyphus_strip", "Sisyphus (compact strip)"),
                ("title", "LAUNCHPAD title"), ("clock", "Clock"), ("campsite", "Campsite"),
                ("fisherman", "Old man fishing"), ("globe", "Rotating globe"), ("saturn", "Saturn"),
                ("storm", "Storm")]
ART_CLASSES = {"title": "Title", "clock": "Clock", "campsite": "Campsite", "fisherman": "Fisherman",
               "globe": "Globe", "saturn": "Saturn", "storm": "Storm"}

EXAMPLE_ART = """fps 6
        /\\
       /  \\
      | LP |
      |    |
     /|    |\\
    /_|____|_\\
       '  '
       ;  ;
      ' '' '
---frame---
        /\\
       /  \\
      | LP |
      |    |
     /|    |\\
    /_|____|_\\
       ;  ;
      ' ;; '
       '  '
---frame---
        /\\
       /  \\
      | LP |
      |    |
     /|    |\\
    /_|____|_\\
       '  '
      ; '' ;
       ;  ;
"""


def art_dir() -> Path:
    p = data_dir() / "art"
    p.mkdir(parents=True, exist_ok=True)
    ex = p / "example-rocket.txt"
    if not any(p.glob("*.txt")):
        try:
            ex.write_text(EXAMPLE_ART, encoding="utf-8")
        except OSError:
            pass
    return p


def custom_arts():
    return [(f"custom:{f.name}", f.stem) for f in sorted(art_dir().glob("*.txt"))]


class ArtManager:
    def __init__(self, counter):
        self.counter = counter
        self.cache = {}

    def get(self, key):
        if key in self.cache:
            return self.cache[key]
        try:
            if key == "sisyphus":
                art = SisyphusScene(self.counter)
            elif key == "sisyphus_strip":
                art = SisyphusScene(self.counter, compact=True)
            elif key in ART_CLASSES:
                art = globals()[ART_CLASSES[key]]()
            elif key.startswith("custom:"):
                art = CustomArt(art_dir() / key[7:])
            else:
                return self.get("sisyphus")
        except Exception:  # noqa: BLE001  (e.g. a custom file was deleted)
            return self.get("sisyphus")
        self.cache[key] = art
        return art

    def reload_custom(self):
        for k in [k for k in self.cache if k.startswith("custom:")]:
            del self.cache[k]


def art_label(key):
    names = dict(BUILTIN_ARTS + custom_arts())
    return names.get(key, key)


class BannerWidget(QWidget):
    """The art slot. Its height is a fixed share of the window height (Small/Medium/Large),
    and whichever art is shown scales to fit inside it, so swapping art never moves the
    rest of the screen."""
    SPEEDS = {0: 160, 1: 100, 2: 60}
    SIZES = {"small": 0.17, "medium": 0.26, "large": 0.38}
    HIDDEN_H = 30

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.settings = win.store.settings
        self.key, self.art = None, None
        self._font = mono_font(12)
        self._cw, self._lh, self._win_h = 7.0, 14.0, 840
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn = QToolButton(self)
        self.btn.setObjectName("artBtn")
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.clicked.connect(self._button)
        self.choose()

    # ---- state
    def hidden_art(self):
        return bool(self.settings.get("banner_hidden"))

    def choose(self):
        small = not (self.win.isMaximized() or self.win.isFullScreen())
        key = self.settings.get("art", "sisyphus")
        alt = self.settings.get("art_small", "same")
        if small and alt != "same":
            key = alt
        if key != self.key:
            self.key = key
            self.art = self.win.arts.get(key)
            if hasattr(self, "timer"):
                self.apply_settings()
        self._fit()
        self.update()

    def set_window_height(self, h):
        self._win_h = h
        self._fit()

    def apply_settings(self):
        animate = self.settings.get("animation", True)
        live = getattr(self.art, "live", False)      # the clock keeps time even when paused
        self.timer.setInterval(self.SPEEDS.get(self.settings.get("anim_speed", 1), 100) if animate else 1000)
        run = (animate or live) and not self.hidden_art() and self.isVisible()
        self.timer.start() if run else self.timer.stop()
        self.btn.setText("SHOW ART" if self.hidden_art() else "ART ▾")
        self.btn.adjustSize()
        self._place_btn()
        self._fit()
        self.update()

    def _set(self, k, v):
        self.settings[k] = v
        self.win.store.save()
        self.choose()
        self.apply_settings()

    def _tick(self):
        if self.art is not None:
            self.art.tick()
        self.update()

    # ---- geometry
    def _fit(self):
        if self.hidden_art():
            self.setFixedHeight(self.HIDDEN_H)
            return
        frac = self.SIZES.get(self.settings.get("banner_size", "medium"), 0.26)
        h = int(max(90, min(560, self._win_h * frac)))
        self.setFixedHeight(h)
        if self.art is None:
            return
        rows = self.art.H + 1.7
        avail_w, avail_h = max(50, self.width() - 16), h - 6
        px = 5
        for size in range(28, 4, -1):
            fm = QFontMetricsF(mono_font(size))
            if fm.horizontalAdvance("M") * self.art.W <= avail_w and fm.height() * 0.92 * rows <= avail_h:
                px = size
                break
        self._font = mono_font(px)
        fm = QFontMetricsF(self._font)
        self._cw, self._lh = fm.horizontalAdvance("M"), fm.height() * 0.92

    def _place_btn(self):
        self.btn.move(self.width() - self.btn.width() - 2, 2)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()
        self._place_btn()

    def showEvent(self, e):
        super().showEvent(e)
        self.apply_settings()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.timer.stop()

    # ---- drawing
    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#000"))
        if self.hidden_art():
            p.setFont(mono_font(12))
            p.setPen(QColor("#555"))
            p.drawText(QRectF(0, 0, self.width() - self.btn.width() - 12, self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       f"[+] {art_label(self.key).upper()} (hidden) " + "─" * 200)
            p.end()
            return
        a = self.art
        p.setFont(self._font)
        fm = QFontMetricsF(self._font)
        art_w = self._cw * a.W
        total_h = self._lh * (a.H + 1.7)
        left = (self.width() - art_w) / 2
        y = (self.height() - total_h) / 2 + fm.ascent()
        p.setPen(QColor("#f2f2f2"))
        for line in a.render():
            p.drawText(QPointF(left, y), line)
            y += self._lh
        y += self._lh * 0.7
        cl, cr = a.captions()
        p.setPen(QColor("#8a8a8a"))
        p.drawText(QPointF(left, y), cl)
        if cr:
            p.drawText(QPointF(left + art_w - fm.horizontalAdvance(cr), y), cr)
        p.end()

    # ---- menu
    def _button(self):
        if self.hidden_art():
            self._set("banner_hidden", False)
            return
        m = QMenu(self)
        arts = BUILTIN_ARTS + custom_arts()

        def art_group(menu, setting, extra_same=False):
            current = self.settings.get(setting, "sisyphus")
            if extra_same:
                act = menu.addAction("Same as above")
                act.setCheckable(True)
                act.setChecked(current == "same")
                act.triggered.connect(lambda _=False: self._set(setting, "same"))
                menu.addSeparator()
            for i, (k, name) in enumerate(arts):
                if i == len(BUILTIN_ARTS) and len(arts) > len(BUILTIN_ARTS):
                    menu.addSeparator()
                act = menu.addAction(name)
                act.setCheckable(True)
                act.setChecked(current == k)
                act.triggered.connect(lambda _=False, kk=k: self._set(setting, kk))

        hdr = m.addAction("ART")
        hdr.setEnabled(False)
        art_group(m, "art")
        m.addSeparator()
        small = m.addMenu("When the window isn't maximised")
        art_group(small, "art_small", extra_same=True)
        size = m.addMenu("Size")
        for k, name in (("small", "Small"), ("medium", "Medium"), ("large", "Large")):
            act = size.addAction(name)
            act.setCheckable(True)
            act.setChecked(self.settings.get("banner_size", "medium") == k)
            act.triggered.connect(lambda _=False, kk=k: self._set("banner_size", kk))
        speed = m.addMenu("Speed")
        for k, name in ((0, "Slow"), (1, "Normal"), (2, "Fast")):
            act = speed.addAction(name)
            act.setCheckable(True)
            act.setChecked(self.settings.get("anim_speed", 1) == k)
            act.triggered.connect(lambda _=False, kk=k: self._set("anim_speed", kk))
        pause = m.addAction("Pause animation")
        pause.setCheckable(True)
        pause.setChecked(not self.settings.get("animation", True))
        pause.triggered.connect(lambda on: self._set("animation", not on))
        m.addSeparator()
        m.addAction("Hide art", lambda: self._set("banner_hidden", True))
        m.addAction("Open custom art folder", lambda: Launcher.open_target(str(art_dir())))

        def reload():
            self.win.arts.reload_custom()
            self.key = None
            self.choose()
            self.win.flash(f"Custom art reloaded ({len(custom_arts())} files)")
        m.addAction("Reload custom art", reload)
        m.exec(self.btn.mapToGlobal(QPoint(0, self.btn.height())))

    def mouseDoubleClickEvent(self, e):
        if self.hidden_art():
            self._set("banner_hidden", False)


# ============================================================ tiles & sections
class Tile(QPushButton):
    def __init__(self, win, item, project_id=None, in_pins=False):
        super().__init__()
        self.win, self.item, self.project_id, self.in_pins = win, item, project_id, in_pins
        self._press = None
        missing = not target_exists(item)
        self.setObjectName("tile")
        self.setProperty("missing", "true" if missing else "false")
        self.setFixedSize(212, 40)
        self.setIconSize(QSize(20, 20))
        self.setIcon(QIcon(item_pixmap(item, missing)))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        name = item.get("name") or "untitled"
        self.setText(" " + self.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, 150))
        detail = item_detail(item)
        tip = f"{name}\n{detail}"
        if missing:
            tip += "\n\nCan't find this any more. Right-click → Edit to re-point it."
        elif project_id is None:
            tip += ("\n\nDrag to another section to move it, or out to your desktop/Explorer/an app "
                    "to use a copy there.")
        self.setToolTip(tip)
        self.search_key = f"{name} {detail}".lower()
        self.clicked.connect(lambda: win.launch(item))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    # drag to move between sections / reorder
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.project_id is None:
            self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if (self._press is not None and e.buttons() & Qt.MouseButton.LeftButton
                and (e.position().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance()):
            hot = self._press
            self._press = None
            self.setDown(False)
            md = QMimeData()
            md.setData(MIME_ITEM, self.item["id"].encode())
            md.setData(MIME_ITEM + "-from", b"pins" if self.in_pins else b"section")
            # also offer the real file/folder/link so it can be dropped on the desktop,
            # into Explorer, an email, a browser upload box, Discord…
            t = expand(self.item.get("target", ""))
            if self.item.get("kind") != "action":
                if is_local_target(self.item) and os.path.exists(t):
                    md.setUrls([QUrl.fromLocalFile(t)])
                elif is_web(t):
                    md.setUrls([QUrl(t)])
                    md.setText(t)
            drag = QDrag(self)
            drag.setMimeData(md)
            drag.setPixmap(self.grab())
            drag.setHotSpot(hot)
            # Copy (or Link with Alt) only, never Move, so the original file always stays put
            drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.LinkAction, Qt.DropAction.CopyAction)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._press = None
        super().mouseReleaseEvent(e)

    def _menu(self, pos):
        w, it = self.win, self.item
        m = QMenu(self)
        m.addAction("Open", lambda: w.launch(it))
        loc = m.addAction("Open file location", lambda: open_location(it.get("target", "")))
        loc.setEnabled(it.get("kind") != "action" and is_local_target(it))
        m.addAction("Edit…", lambda: w.edit_item(it, self.project_id))
        m.addSeparator()
        if self.project_id:
            m.addAction("Remove from project", lambda: w.remove_project_item(self.project_id, it["id"]))
        else:
            if w.store.is_pinned(it["id"]):
                m.addAction("Unpin from top", lambda: w.unpin_item(it["id"]))
            else:
                m.addAction("Pin to top", lambda: w.pin_item(it["id"]))
            mv = m.addMenu("Move to section")
            for key, title in CATEGORIES:
                if key != it.get("category"):
                    mv.addAction(title.title(), lambda k=key: w.set_category(it, k))
            pj = m.addMenu("Pin to project")
            projects = w.store.projects()
            if not projects:
                pj.addAction("(no projects yet)").setEnabled(False)
            for p in projects:
                pj.addAction(p["name"], lambda pid=p["id"]: w.pin_to_project(it, pid))
            m.addSeparator()
            m.addAction("Remove", lambda: w.remove_item(it))
        m.exec(self.mapToGlobal(pos))


def item_detail(item):
    if item.get("kind") == "action":
        return " → ".join(
            (f"wait {s.get('seconds')}s" if s.get("type") == "wait"
             else Path(s.get("target", "")).name or s.get("target", ""))
            for s in item.get("steps", []))
    return item.get("target", "")


class ProjectTile(QPushButton):
    """On the home screen. Click shows the project's pinned items in a list."""

    def __init__(self, win, project):
        super().__init__()
        self.win, self.project = win, project
        self.setObjectName("tile")
        self.setFixedSize(212, 40)
        self.setIconSize(QSize(20, 20))
        self.setIcon(QIcon(glyph_pixmap("project")))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        n_items = len(project.get("items", []))
        open_todos = sum(1 for t in project.get("todos", []) if not t.get("done"))
        label = project["name"] + (f"  [{n_items}]" if n_items else "")
        self.setText(" " + self.fontMetrics().elidedText(label, Qt.TextElideMode.ElideRight, 150))
        self.setToolTip(f"{project['name']}\n{n_items} pinned · {open_todos} open tasks · "
                        f"edited {fmt_date(project.get('updated'))}\n\nClick to see its pinned items.")
        text = " ".join([project["name"], project.get("notes", "")]
                        + [t["text"] for t in project.get("todos", [])]
                        + [i.get("name", "") for i in project.get("items", [])])
        self.search_key = text.lower()
        self.clicked.connect(self._popup)

    def _popup(self):
        w, p = self.win, self.win.store.get_project(self.project["id"])
        if not p:
            return
        m = QMenu(self)
        m.setObjectName("projectMenu")
        title = m.addAction(p["name"].upper())
        title.setEnabled(False)
        items = p.get("items", [])
        if not items:
            m.addAction("(nothing pinned yet: drop files on the project page)").setEnabled(False)
        for it in items:
            missing = not target_exists(it)
            act = m.addAction(QIcon(item_pixmap(it, missing)), it.get("name") or "untitled")
            act.setToolTip(item_detail(it))
            act.triggered.connect(lambda _=False, i=it: w.launch(i))
        m.setToolTipsVisible(True)
        m.addSeparator()
        if items:
            m.addAction(f"Open all {len(items)} pinned", lambda: [w.launcher.run(i) for i in items])
        open_todos = [t["text"] for t in p.get("todos", []) if not t.get("done")]
        if open_todos:
            m.addAction(f"{len(open_todos)} open task{'s' if len(open_todos) != 1 else ''}"
                        f": {open_todos[0][:40]}").setEnabled(False)
        m.addAction("Open project page →", lambda: w.show_project(p["id"]))
        m.exec(self.mapToGlobal(QPoint(0, self.height())))


def add_tile(text, slot):
    b = QPushButton(text)
    b.setObjectName("addTile")
    b.setFixedSize(40, 40) if text == "+" else b.setFixedHeight(40)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setToolTip("Add")
    b.clicked.connect(slot)
    return b


class Section(QFrame):
    def __init__(self, win, key, title, accept_drops=True, show_empty=True, empty_text=None):
        super().__init__()
        self.win, self.key, self.title, self.show_empty = win, key, title, show_empty
        self.setObjectName("section")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 6, 0, 6)
        v.setSpacing(8)
        self.header = QPushButton()
        self.header.setObjectName("sectionToggle")
        self.header.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setToolTip("Click to collapse / expand")
        self.header.clicked.connect(self.toggle)
        self.body = QWidget()
        self.flow = FlowLayout(self.body)
        self.empty = QLabel(empty_text or "empty. Drag something onto this section, or click +")
        self.empty.setObjectName("dim")
        v.addWidget(self.header)
        v.addWidget(self.body)
        v.addWidget(self.empty)
        self.tiles, self.add_btn, self._filtering = [], None, False
        self.setAcceptDrops(accept_drops)

    @property
    def collapsed(self):
        return self.key in self.win.store.settings.setdefault("collapsed", [])

    def toggle(self):
        c = self.win.store.settings.setdefault("collapsed", [])
        if self.key in c:
            c.remove(self.key)
        else:
            c.append(self.key)
        self.win.store.save()
        self._update()

    def _update(self):
        mark = "[+]" if self.collapsed else "[-]"
        self.header.setText(f"{mark} {self.title} ({len(self.tiles)}) " + "─" * 300)
        open_ = not self.collapsed or self._filtering
        self.body.setVisible(open_)
        self.empty.setVisible(open_ and self.show_empty and not self.tiles and not self._filtering)

    def set_tiles(self, tiles, add_btn=None):
        while self.flow.count():
            w = self.flow.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        self.tiles, self.add_btn = tiles, add_btn
        for t in tiles:
            self.flow.addWidget(t)
        if add_btn:
            self.flow.addWidget(add_btn)
        self._update()

    def apply_filter(self, text):
        self._filtering = bool(text)
        vis = []
        for t in self.tiles:
            ok = not text or text in t.search_key
            t.setVisible(ok)
            if ok:
                vis.append(t)
        if self.add_btn:
            self.add_btn.setVisible(not text)
        self.setVisible(bool(vis) or not text)
        self._update()
        self.body.updateGeometry()
        return vis

    def _before_id(self, pos):
        """Item id of the tile the drop lands before (None = end)."""
        p = self.body.mapFrom(self, pos)
        for t in self.tiles:
            if not t.isVisible():
                continue
            g = t.geometry()
            if p.y() < g.top():
                return t.item["id"]
            if g.top() <= p.y() <= g.bottom() and p.x() < g.center().x():
                return t.item["id"]
        return None

    def _accepts(self, md):
        if md.hasFormat(MIME_ITEM):
            return self.key in CAT_NAMES or self.key == "pinned"
        return self.win.mime_ok(md)

    def _mark(self, on):
        self.setProperty("drop", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):
        if self._accepts(e.mimeData()):
            e.acceptProposedAction()
            self._mark(True)

    def dragMoveEvent(self, e):
        if self._accepts(e.mimeData()):
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._mark(False)

    def dropEvent(self, e):
        self._mark(False)
        md = e.mimeData()
        if md.hasFormat(MIME_ITEM):
            iid = bytes(md.data(MIME_ITEM)).decode()
            before = self._before_id(e.position().toPoint())
            e.acceptProposedAction()
            # finish the drag before rebuilding the tiles
            if self.key == "pinned":
                QTimer.singleShot(0, lambda: self.win.pin_item(iid, before))
            else:
                QTimer.singleShot(0, lambda: self.win.move_item_to(iid, self.key, before))
            return
        e.acceptProposedAction()
        cat = self.key if self.key in CAT_NAMES else None
        data = QMimeData()
        for fmt in md.formats():
            data.setData(fmt, md.data(fmt))
        QTimer.singleShot(0, lambda: self.win.handle_drop(data, category=cat, pin=self.key == "pinned"))


# ============================================================ home
class HomePage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 12, 22, 6)
        v.setSpacing(8)
        self.banner = BannerWidget(win)
        v.addWidget(self.banner)
        self.due = Section(win, "due", "DUE SOON && URGENT", accept_drops=False, show_empty=False)
        v.addWidget(self.due)
        self.pins = Section(win, "pinned", "PINNED", accept_drops=True,
                            empty_text="right-click anything → Pin to top, or drag a tile here")
        v.addWidget(self.pins)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.textChanged.connect(self.apply_filter)
        self.search.returnPressed.connect(self.open_top)
        self.search.installEventFilter(self)
        self.search.setAcceptDrops(False)
        v.addWidget(self.search)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        self.iv = QVBoxLayout(inner)
        self.iv.setContentsMargins(0, 0, 8, 12)
        self.iv.setSpacing(2)
        self.recent = Section(win, "recent", "RECENT", accept_drops=False, show_empty=False)
        self.iv.addWidget(self.recent)
        self.sections = {}
        for key, title in CATEGORIES:
            s = Section(win, key, title)
            self.sections[key] = s
            self.iv.addWidget(s)
        self.sections["projects"] = Section(win, "projects", "PROJECTS", accept_drops=False, show_empty=False)
        self.iv.addWidget(self.sections["projects"])
        self.iv.addStretch(1)
        self.scroll.setWidget(inner)
        v.addWidget(self.scroll, 1)
        self._top = None

    def eventFilter(self, obj, ev):
        if obj is self.search and ev.type() == ev.Type.KeyPress and ev.key() == Qt.Key.Key_Escape:
            if self.search.text():
                self.search.clear()
            else:
                self.win.hide_window()
            return True
        return super().eventFilter(obj, ev)

    def refresh_due(self):
        st = self.win.store
        hot = [t for t in st.tasks() if task_hot(t)]
        hot.sort(key=lambda t: (parse_day(t.get("due")) or date.max, -t.get("urgency", 1)))
        soon = {date.today().isoformat(), (date.today() + timedelta(days=1)).isoformat()}
        rems = sorted((r for r in st.reminders() if r.get("date") in soon),
                      key=lambda r: (r.get("date"), r.get("time") or "99"))
        chips = [ReminderChip(self.win, r) for r in rems] + [TaskChip(self.win, t) for t in hot]
        self.due.set_tiles(chips)
        self.due.setVisible(bool(chips))

    def refresh(self):
        st = self.win.store
        self.refresh_due()
        self.pins.set_tiles([Tile(self.win, i, in_pins=True) for i in st.pins()])
        self.refresh_recent(apply=False)
        for key, _ in CATEGORIES:
            tiles = [Tile(self.win, i) for i in st.items(key)]
            self.sections[key].set_tiles(tiles, add_tile("+", lambda k=key: self.win.add_item(category=k)))
        projects = [p for p in st.projects() if p.get("status") != "done"]
        projects.sort(key=lambda p: -p.get("updated", 0))
        self.sections["projects"].set_tiles([ProjectTile(self.win, p) for p in projects],
                                            add_tile("+ new project", self.win.new_project))
        self.apply_filter(self.search.text())

    def refresh_recent(self, apply=True):
        used = [i for i in self.win.store.items() if i.get("last_used")]
        used.sort(key=lambda i: -i["last_used"])
        self.recent.set_tiles([Tile(self.win, i) for i in used[:8]])
        if apply:
            self.apply_filter(self.search.text())

    def apply_filter(self, text):
        text = text.strip().lower()
        self._top = None
        for key in [k for k, _ in CATEGORIES] + ["projects"]:
            vis = self.sections[key].apply_filter(text)
            if vis and self._top is None:
                self._top = vis[0]
        self.recent.apply_filter("")
        self.recent.setVisible(not text and bool(self.recent.tiles))

    def open_top(self):
        if self._top is not None:
            self._top.click()

    def scroll_to(self, key):
        sec = self.sections.get(key)
        if sec:
            QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(max(0, sec.y() - 4)))


# ============================================================ projects
class ProjectDetail(QWidget):
    def __init__(self, win, page):
        super().__init__()
        self.win, self.page, self.pid, self._loading = win, page, None, False
        self.setAcceptDrops(True)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(600)
        self._timer.timeout.connect(self.flush)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        back = QPushButton("‹ ALL PROJECTS")
        back.clicked.connect(page.back)
        self.name = QLineEdit()
        self.name.setObjectName("projName")
        self.name.textEdited.connect(self.changed)
        self.status = QComboBox()
        self.status.addItems(["active", "paused", "done"])
        self.status.currentTextChanged.connect(self.changed)
        openall = QPushButton("OPEN ALL PINNED")
        openall.setToolTip("Re-open every pinned file, folder and link to pick up where you left off")
        openall.clicked.connect(self.open_all)
        delete = QPushButton("DELETE")
        delete.clicked.connect(self.delete)
        top.addWidget(back)
        top.addSpacing(10)
        top.addWidget(self.name, 1)
        top.addWidget(self.status)
        top.addWidget(openall)
        top.addWidget(delete)
        v.addLayout(top)
        self.meta = QLabel()
        self.meta.setObjectName("dim")
        v.addWidget(self.meta)

        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 6, 8, 0)
        lv.addWidget(self._label("NOTES"))
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Notes, decisions, links, where you left off…\n\nTip: drop a file here to paste its path.")
        self.notes.textChanged.connect(self.changed)
        lv.addWidget(self.notes, 1)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 6, 0, 0)
        rv.addWidget(self._label("TO-DO"))
        self.new_todo = QLineEdit()
        self.new_todo.setPlaceholderText("add a task and press Enter")
        self.new_todo.returnPressed.connect(self.add_todo)
        rv.addWidget(self.new_todo)
        self.todos = QListWidget()
        self.todos.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.todos.itemChanged.connect(self._todo_changed)
        self.todos.model().rowsMoved.connect(self.changed)
        self.todos.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.todos.customContextMenuRequested.connect(self._todo_menu)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.todos, self._delete_todo,
                  context=Qt.ShortcutContext.WidgetShortcut)
        rv.addWidget(self.todos, 1)
        prow = QHBoxLayout()
        self.pin_label = self._label("PINNED")
        prow.addWidget(self.pin_label)
        prow.addStretch(1)
        addpin = QPushButton("+ PIN")
        addpin.clicked.connect(lambda: self.win.add_item(project_id=self.pid))
        prow.addWidget(addpin)
        rv.addSpacing(6)
        rv.addLayout(prow)
        self.pinned = QListWidget()
        self.pinned.setObjectName("pinnedList")
        self.pinned.setIconSize(QSize(20, 20))
        self.pinned.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.pinned.setWordWrap(False)
        self.pinned.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.pinned.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pinned.itemClicked.connect(self._open_pinned)
        self.pinned.model().rowsMoved.connect(self._pinned_reordered)
        self.pinned.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.pinned.customContextMenuRequested.connect(self._pinned_menu)
        self.pinned.setToolTip("Click to open \u00b7 drag to reorder \u00b7 right-click for more\n"
                               "Drop files, folders or links anywhere on this page to pin them")
        rv.addWidget(self.pinned, 1)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([560, 440])
        v.addWidget(split, 1)

    @staticmethod
    def _label(text):
        lab = QLabel(text)
        lab.setObjectName("sectionHeader")
        return lab

    def project(self):
        return self.win.store.get_project(self.pid) if self.pid else None

    def load(self, pid):
        self.flush()
        self.pid = pid
        p = self.project()
        if not p:
            return
        self._loading = True
        self.name.setText(p["name"])
        self.status.setCurrentText(p.get("status", "active"))
        self.notes.setPlainText(p.get("notes", ""))
        self.todos.clear()
        for t in p.get("todos", []):
            self._add_todo_item(t["text"], t.get("done", False))
        self.fill_pinned()
        self.meta.setText(f"created {fmt_date(p.get('created'))} · last edited {fmt_date(p.get('updated'))}")
        self._loading = False

    def _add_todo_item(self, text, done):
        it = QListWidgetItem(text)
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable
                    | Qt.ItemFlag.ItemIsDragEnabled)
        it.setCheckState(Qt.CheckState.Checked if done else Qt.CheckState.Unchecked)
        self._style_todo(it)
        self.todos.addItem(it)

    def _style_todo(self, it):
        done = it.checkState() == Qt.CheckState.Checked
        f = it.font()
        f.setStrikeOut(done)
        it.setFont(f)
        it.setForeground(QColor("#666" if done else "#e6e6e6"))

    def _todo_changed(self, it):
        if self._loading:
            return
        self._loading = True
        self._style_todo(it)
        self._loading = False
        self.changed()

    def add_todo(self):
        t = self.new_todo.text().strip()
        if t:
            self._loading = True
            self._add_todo_item(t, False)
            self._loading = False
            self.new_todo.clear()
            self.changed()

    def _delete_todo(self):
        for it in self.todos.selectedItems():
            self.todos.takeItem(self.todos.row(it))
        self.changed()

    def _todo_menu(self, pos):
        m = QMenu(self)
        m.addAction("Delete task", self._delete_todo)

        def clear_done():
            for i in reversed(range(self.todos.count())):
                if self.todos.item(i).checkState() == Qt.CheckState.Checked:
                    self.todos.takeItem(i)
            self.changed()
        m.addAction("Clear completed", clear_done)
        m.exec(self.todos.mapToGlobal(pos))

    def fill_pinned(self):
        self.pinned.clear()
        p = self.project()
        if not p:
            return
        items = p.get("items", [])
        self.pin_label.setText(f"PINNED ({len(items)})")
        for it in items:
            missing = not target_exists(it)
            name = it.get("name") or "untitled"
            row = QListWidgetItem(QIcon(item_pixmap(it, missing)),
                                  f"{name}{'   (missing)' if missing else ''}\n{item_detail(it)}")
            row.setData(Qt.ItemDataRole.UserRole, it["id"])
            row.setToolTip(item_detail(it))
            row.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
            if missing:
                row.setForeground(QColor("#666"))
            self.pinned.addItem(row)
        if not items:
            row = QListWidgetItem("Nothing pinned yet.\nDrop files, folders or links anywhere on this page, or click + PIN.")
            row.setFlags(Qt.ItemFlag.NoItemFlags)
            row.setForeground(QColor("#666"))
            self.pinned.addItem(row)

    def _pinned_item(self, row):
        p = self.project()
        iid = row.data(Qt.ItemDataRole.UserRole) if row else None
        if not p or not iid:
            return None
        return next((i for i in p.get("items", []) if i["id"] == iid), None)

    def _open_pinned(self, row):
        it = self._pinned_item(row)
        if it:
            self.win.launch(it)

    def _pinned_reordered(self, *_):
        p = self.project()
        if not p:
            return
        by_id = {i["id"]: i for i in p.get("items", [])}
        order = [self.pinned.item(n).data(Qt.ItemDataRole.UserRole) for n in range(self.pinned.count())]
        p["items"] = [by_id[i] for i in order if i in by_id]
        self.win.store.save()

    def _pinned_menu(self, pos):
        it = self._pinned_item(self.pinned.itemAt(pos))
        if not it:
            return
        m = QMenu(self)
        m.addAction("Open", lambda: self.win.launch(it))
        loc = m.addAction("Open file location", lambda: open_location(it.get("target", "")))
        loc.setEnabled(it.get("kind") != "action" and is_local_target(it))
        m.addAction("Edit\u2026", lambda: self.win.edit_item(it, self.pid))
        m.addSeparator()
        m.addAction("Remove from project", lambda: self.win.remove_project_item(self.pid, it["id"]))
        m.exec(self.pinned.mapToGlobal(pos))

    def changed(self, *_):
        if not self._loading and self.pid:
            self._timer.start()

    def flush(self):
        self._timer.stop()
        p = self.project()
        if not p:
            return
        p["name"] = self.name.text().strip() or "Untitled project"
        p["status"] = self.status.currentText()
        p["notes"] = self.notes.toPlainText()
        p["todos"] = [{"text": self.todos.item(i).text(),
                       "done": self.todos.item(i).checkState() == Qt.CheckState.Checked}
                      for i in range(self.todos.count())]
        p["updated"] = now()
        self.win.store.save()
        self.win.home_dirty = True

    def open_all(self):
        p = self.project()
        if p:
            for it in p.get("items", []):
                self.win.launcher.run(it)
            self.win.flash(f"Opening {len(p.get('items', []))} pinned items")

    def delete(self):
        p = self.project()
        if not p:
            return
        r = QMessageBox.question(self, "Delete project", f"Delete '{p['name']}' and its notes?")
        if r == QMessageBox.StandardButton.Yes:
            self.win.store.remove_project(self.pid)
            self.pid = None
            self.win.home_dirty = True
            self.page.back()

    def dragEnterEvent(self, e):
        if self.win.mime_ok(e.mimeData()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.win.handle_drop(e.mimeData(), project_id=self.pid)
        e.acceptProposedAction()


class ProjectsPage(QStackedWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        lv = QWidget()
        l = QVBoxLayout(lv)
        l.setContentsMargins(26, 22, 26, 10)
        top = QHBoxLayout()
        title = QLabel("PROJECTS")
        title.setObjectName("pageTitle")
        self.show_done = QCheckBox("show finished")
        self.show_done.toggled.connect(self.refresh_list)
        newb = QPushButton("+ NEW PROJECT")
        newb.clicked.connect(win.new_project)
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(self.show_done)
        top.addWidget(newb)
        l.addLayout(top)
        hint = QLabel("Each project keeps its notes, to-do list and pinned files, folders and links together.")
        hint.setObjectName("dim")
        l.addWidget(hint)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        self.flow = FlowLayout(body, spacing=12)
        scroll.setWidget(body)
        l.addWidget(scroll, 1)
        dv = QWidget()
        dl = QVBoxLayout(dv)
        dl.setContentsMargins(26, 18, 26, 10)
        self.detail = ProjectDetail(win, self)
        dl.addWidget(self.detail)
        self.addWidget(lv)
        self.addWidget(dv)

    def refresh_list(self):
        while self.flow.count():
            w = self.flow.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        order = {"active": 0, "paused": 1, "done": 2}
        ps = sorted(self.win.store.projects(),
                    key=lambda p: (order.get(p.get("status"), 0), -p.get("updated", 0)))
        if not self.show_done.isChecked():
            ps = [p for p in ps if p.get("status") != "done"]
        for p in ps:
            todos = p.get("todos", [])
            done = sum(1 for t in todos if t.get("done"))
            first = next((ln.strip() for ln in p.get("notes", "").splitlines() if ln.strip()), "no notes yet")
            fm = self.fontMetrics()
            text = (fm.elidedText(p["name"].upper(), Qt.TextElideMode.ElideRight, 220) + "\n"
                    + f"{p.get('status', 'active')} · {done}/{len(todos)} tasks · {len(p.get('items', []))} pinned\n"
                    + f"edited {fmt_date(p.get('updated'))}\n\n"
                    + fm.elidedText(first, Qt.TextElideMode.ElideRight, 220))
            card = QPushButton(text)
            card.setObjectName("card")
            card.setProperty("done", "true" if p.get("status") == "done" else "false")
            card.setFixedSize(256, 124)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.clicked.connect(lambda _=False, pid=p["id"]: self.open_project(pid))
            self.flow.addWidget(card)
        self.flow.addWidget(add_tile("+ new project", self.win.new_project))

    def open_project(self, pid):
        self.detail.load(pid)
        self.setCurrentIndex(1)

    def back(self):
        self.detail.flush()
        self.refresh_list()
        self.setCurrentIndex(0)


# ============================================================ to-do & calendar
URGENCY_NAMES = {1: "low", 2: "minor", 3: "medium", 4: "high", 5: "critical"}
WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def parse_day(iso):
    try:
        return date.fromisoformat(iso) if iso else None
    except (TypeError, ValueError):
        return None


def due_text(iso):
    d = parse_day(iso)
    if not d:
        return ""
    n = (d - date.today()).days
    if n < 0:
        return f"overdue {-n}d"
    if n == 0:
        return "due today"
    if n == 1:
        return "due tomorrow"
    if n < 7:
        return f"due {d:%a}"
    return f"due {d.day} {d:%b}"


def due_soon(iso, days=2):
    d = parse_day(iso)
    return d is not None and (d - date.today()).days <= days


def task_hot(t):
    return not t.get("done") and (t.get("urgency", 1) >= 5 or due_soon(t.get("due")))


def sort_tasks(tasks, mode):
    far = date.max
    open_ = [t for t in tasks if not t.get("done")]
    done = [t for t in tasks if t.get("done")]
    if mode == "due":
        key = lambda t: (parse_day(t.get("due")) or far, -t.get("urgency", 1))  # noqa: E731
    elif mode == "newest":
        key = lambda t: -t.get("created", 0)  # noqa: E731
    else:
        key = lambda t: (-t.get("urgency", 1), parse_day(t.get("due")) or far, -t.get("created", 0))  # noqa: E731
    return sorted(open_, key=key) + sorted(done, key=lambda t: -t.get("done_at", 0))


def norm_time(text):
    """'930', '9:30', '09:30' -> '09:30'; '' -> ''; None if invalid."""
    t = (text or "").strip().replace(".", ":")
    if not t:
        return ""
    m = re.fullmatch(r"(\d{1,2}):?(\d{2})", t)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None


def qdate(d):
    return QDate(d.year, d.month, d.day)


class UrgencyMeter(QWidget):
    """Five boxes: click box N to set urgency N (1 = least, 5 = most)."""
    changed = Signal(int)

    def __init__(self, level=3, box=12, gap=3, interactive=True):
        super().__init__()
        self.level, self.box, self.gap, self.interactive = level, box, gap, interactive
        self.setFixedSize(5 * box + 4 * gap, box + 2)
        if interactive:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("Urgency: click a box (1 = least, 5 = most)")
        else:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_level(self, level):
        self.level = max(1, min(5, int(level)))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        for i in range(5):
            r = QRectF(i * (self.box + self.gap) + 0.5, 1.5, self.box - 1, self.box - 1)
            on = i < self.level
            p.setPen(QPen(QColor("#fff" if on else "#4a4a4a"), 1))
            p.setBrush(QColor("#fff") if on else Qt.BrushStyle.NoBrush)
            p.drawRect(r)
        p.end()

    def mousePressEvent(self, e):
        if not self.interactive:
            return super().mousePressEvent(e)
        i = int(e.position().x() // (self.box + self.gap)) + 1
        self.set_level(i)
        self.changed.emit(self.level)


class ElidedLabel(QLabel):
    def __init__(self, text=""):
        super().__init__()
        self._full = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setFullText(self, text):
        self._full = text
        self._elide()

    def _elide(self):
        super().setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, max(20, self.width())))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def setText(self, text):
        self._full = text
        self._elide()


class TaskRow(QWidget):
    def __init__(self, page, task):
        super().__init__()
        self.page, self.tid = page, task["id"]
        self.setObjectName("taskRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 5, 8, 5)
        h.setSpacing(10)
        done = bool(task.get("done"))
        self.cb = QCheckBox()
        self.cb.setChecked(done)
        self.cb.setToolTip("Mark done")
        self.cb.toggled.connect(lambda on: page.set_done(self.tid, on))
        self.meter = UrgencyMeter(task.get("urgency", 3))
        self.meter.changed.connect(lambda lvl: page.set_urgency(self.tid, lvl))
        self.title = ElidedLabel(task.get("text", ""))
        f = self.title.font()
        f.setStrikeOut(done)
        self.title.setFont(f)
        if done:
            self.title.setStyleSheet("color:#666;")
        notes = QLabel("[notes]" if task.get("notes", "").strip() else "")
        notes.setObjectName("dim")
        due = QLabel(due_text(task.get("due")) if not done else "done")
        due.setObjectName("hot" if (not done and due_soon(task.get("due"))) else "dim")
        h.addWidget(self.cb)
        h.addWidget(self.meter)
        h.addWidget(self.title, 1)
        h.addWidget(notes)
        h.addWidget(due)


class TodoPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.sel = None
        self._loading = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._commit)
        self._resort = QTimer(self)
        self._resort.setSingleShot(True)
        self._resort.setInterval(900)
        self._resort.timeout.connect(self.refresh)

        v = QVBoxLayout(self)
        v.setContentsMargins(26, 22, 26, 10)
        top = QHBoxLayout()
        title = QLabel("TO-DO")
        title.setObjectName("pageTitle")
        self.counts = QLabel()
        self.counts.setObjectName("dim")
        self.sort = QComboBox()
        for key, name in (("urgency", "sort: urgency"), ("due", "sort: do-by date"), ("newest", "sort: newest")):
            self.sort.addItem(name, key)
        self.sort.setCurrentIndex(max(0, self.sort.findData(win.store.settings.get("todo_sort", "urgency"))))
        self.sort.currentIndexChanged.connect(self._sort_changed)
        self.show_done = QCheckBox("show done")
        self.show_done.toggled.connect(self.refresh)
        top.addWidget(title)
        top.addSpacing(14)
        top.addWidget(self.counts)
        top.addStretch(1)
        top.addWidget(self.sort)
        top.addWidget(self.show_done)
        v.addLayout(top)

        add = QHBoxLayout()
        self.new = QLineEdit()
        self.new.setPlaceholderText("new task… press Enter")
        self.new.returnPressed.connect(self.add)
        self.new_meter = UrgencyMeter(3, box=14)
        addb = QPushButton("+ ADD")
        addb.clicked.connect(self.add)
        add.addWidget(self.new, 1)
        add.addWidget(QLabel("urgency"))
        add.addWidget(self.new_meter)
        add.addWidget(addb)
        v.addLayout(add)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.list = QListWidget()
        self.list.setObjectName("taskList")
        self.list.currentItemChanged.connect(self._current_changed)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.list, self.delete,
                  context=Qt.ShortcutContext.WidgetShortcut)
        split.addWidget(self.list)

        self.detail = QStackedWidget()
        empty = QLabel("Select a task to edit its urgency, do-by date and notes.")
        empty.setObjectName("dim")
        empty.setWordWrap(True)
        empty.setAlignment(Qt.AlignmentFlag.AlignTop)
        empty.setContentsMargins(14, 6, 6, 6)
        self.detail.addWidget(empty)
        form = QWidget()
        fv = QVBoxLayout(form)
        fv.setContentsMargins(14, 0, 0, 0)
        self.d_title = QLineEdit()
        self.d_title.setObjectName("projName")
        self.d_title.textEdited.connect(self._edited)
        fv.addWidget(self.d_title)
        fv.addSpacing(8)
        fv.addWidget(self._h("URGENCY"))
        ur = QHBoxLayout()
        self.d_meter = UrgencyMeter(3, box=20, gap=5)
        self.d_meter.changed.connect(self._edited)
        self.d_urg = QLabel()
        self.d_urg.setObjectName("dim")
        ur.addWidget(self.d_meter)
        ur.addSpacing(10)
        ur.addWidget(self.d_urg)
        ur.addStretch(1)
        fv.addLayout(ur)
        fv.addSpacing(8)
        fv.addWidget(self._h("DO BY"))
        dr = QHBoxLayout()
        self.d_has_due = QCheckBox("set a date")
        self.d_has_due.toggled.connect(self._edited)
        self.d_due = QDateEdit()
        self.d_due.setCalendarPopup(True)
        self.d_due.setDisplayFormat("ddd dd MMM yyyy")
        self.d_due.calendarWidget().setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        self.d_due.dateChanged.connect(lambda _: self._edited(from_date=True))
        dr.addWidget(self.d_has_due)
        dr.addWidget(self.d_due)
        for label, days in (("TODAY", 0), ("TOMORROW", 1), ("+1 WEEK", 7)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, n=days: self._quick_due(n))
            dr.addWidget(b)
        dr.addStretch(1)
        fv.addLayout(dr)
        self.d_due_text = QLabel()
        self.d_due_text.setObjectName("dim")
        fv.addWidget(self.d_due_text)
        fv.addSpacing(8)
        fv.addWidget(self._h("NOTES"))
        self.d_notes = QPlainTextEdit()
        self.d_notes.setPlaceholderText("Details, links, steps…")
        self.d_notes.textChanged.connect(self._edited)
        fv.addWidget(self.d_notes, 1)
        bottom = QHBoxLayout()
        self.d_meta = QLabel()
        self.d_meta.setObjectName("dim")
        self.d_done = QPushButton("MARK DONE")
        self.d_done.clicked.connect(lambda: self.set_done(self.sel, not self._task(self.sel).get("done")))
        delb = QPushButton("DELETE")
        delb.clicked.connect(self.delete)
        bottom.addWidget(self.d_meta, 1)
        bottom.addWidget(self.d_done)
        bottom.addWidget(delb)
        fv.addLayout(bottom)
        self.detail.addWidget(form)
        split.addWidget(self.detail)
        split.setSizes([620, 380])
        v.addWidget(split, 1)

    @staticmethod
    def _h(text):
        lab = QLabel(text)
        lab.setObjectName("sectionHeader")
        return lab

    def _task(self, tid):
        return self.win.store.get_task(tid) if tid else None

    # ---- list
    def refresh(self):
        st = self.win.store
        tasks = st.tasks()
        mode = self.sort.currentData()
        shown = sort_tasks(tasks, mode)
        if not self.show_done.isChecked():
            shown = [t for t in shown if not t.get("done")]
        n_open = sum(1 for t in tasks if not t.get("done"))
        n_hot = sum(1 for t in tasks if task_hot(t))
        self.counts.setText(f"{n_open} open · {n_hot} urgent or due soon")
        self._loading = True
        self.list.clear()
        keep = None
        for t in shown:
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, t["id"])
            it.setSizeHint(QSize(100, 38))
            self.list.addItem(it)
            self.list.setItemWidget(it, TaskRow(self, t))
            if t["id"] == self.sel:
                keep = it
        if not shown:
            it = QListWidgetItem("Nothing to do. Add a task above.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            it.setForeground(QColor("#666"))
            self.list.addItem(it)
        if keep is not None:
            self.list.setCurrentItem(keep)
        self._loading = False
        if keep is None and self.sel and not self._task(self.sel):
            self.sel = None
            self.detail.setCurrentIndex(0)

    def _sort_changed(self, *_):
        self.win.store.settings["todo_sort"] = self.sort.currentData()
        self.win.store.save()
        self.refresh()

    def _current_changed(self, cur, _prev):
        if self._loading or cur is None:
            return
        tid = cur.data(Qt.ItemDataRole.UserRole)
        if tid:
            self.load(tid)

    def select(self, tid):
        t = self._task(tid)
        if not t:
            return
        if t.get("done") and not self.show_done.isChecked():
            self.show_done.setChecked(True)
        self.sel = tid
        self.refresh()
        self.load(tid)

    # ---- detail
    def load(self, tid):
        self._commit()
        t = self._task(tid)
        if not t:
            return
        self.sel = tid
        self._loading = True
        self.d_title.setText(t.get("text", ""))
        self.d_meter.set_level(t.get("urgency", 3))
        self.d_urg.setText(URGENCY_NAMES.get(t.get("urgency", 3), ""))
        d = parse_day(t.get("due"))
        self.d_has_due.setChecked(d is not None)
        self.d_due.setDate(qdate(d or date.today()))
        self.d_due.setEnabled(d is not None)
        self.d_due_text.setText(due_text(t.get("due")))
        self.d_notes.setPlainText(t.get("notes", ""))
        created = datetime.fromtimestamp(t.get("created", now())).strftime("%d %b %Y")
        self.d_meta.setText(f"added {created}")
        self.d_done.setText("REOPEN" if t.get("done") else "MARK DONE")
        self.detail.setCurrentIndex(1)
        self._loading = False

    def _quick_due(self, days):
        if not self.sel:
            return
        self._loading = True
        self.d_has_due.setChecked(True)
        self.d_due.setDate(qdate(date.today() + timedelta(days=days)))
        self._loading = False
        self._edited()

    def _edited(self, *_, from_date=False):
        if self._loading or not self.sel:
            return
        if from_date and not self.d_has_due.isChecked():
            self._loading = True
            self.d_has_due.setChecked(True)
            self._loading = False
        t = self._task(self.sel)
        if not t:
            return
        t["text"] = self.d_title.text().strip() or "untitled"
        t["urgency"] = self.d_meter.level
        t["due"] = self.d_due.date().toPython().isoformat() if self.d_has_due.isChecked() else ""
        t["notes"] = self.d_notes.toPlainText()
        self.d_due.setEnabled(self.d_has_due.isChecked())
        self.d_urg.setText(URGENCY_NAMES.get(t["urgency"], ""))
        self.d_due_text.setText(due_text(t["due"]))
        self._save_timer.start()

    def _commit(self):
        if self._save_timer.isActive():
            self._save_timer.stop()
            self.win.store.save()
            self.refresh()
            self.win.tasks_changed(skip=self)

    # ---- actions
    def add(self):
        text = self.new.text().strip()
        if not text:
            return
        t = self.win.store.add_task(text, urgency=self.new_meter.level)
        self.new.clear()
        self.sel = t["id"]
        self.refresh()
        self.load(t["id"])
        self.win.tasks_changed(skip=self)

    def set_done(self, tid, on):
        t = self._task(tid)
        if not t:
            return
        t["done"] = bool(on)
        t["done_at"] = now() if on else 0
        self.win.store.save()
        if tid == self.sel:
            self.d_done.setText("REOPEN" if on else "MARK DONE")
        QTimer.singleShot(250, self.refresh)
        self.win.tasks_changed(skip=self)
        if on:
            self.win.flash(f"Done: {t.get('text')}")

    def set_urgency(self, tid, level):
        t = self._task(tid)
        if t:
            t["urgency"] = level
            self.win.store.save()
            if tid == self.sel:
                self._loading = True
                self.d_meter.set_level(level)
                self.d_urg.setText(URGENCY_NAMES.get(level, ""))
                self._loading = False
            self._resort.start()
            self.win.tasks_changed(skip=self)

    def delete(self):
        t = self._task(self.sel)
        if not t:
            return
        if QMessageBox.question(self, "Delete task", f"Delete '{t.get('text')}'?") != QMessageBox.StandardButton.Yes:
            return
        self._save_timer.stop()
        self.win.store.remove_task(t["id"])
        self.sel = None
        self.detail.setCurrentIndex(0)
        self.refresh()
        self.win.tasks_changed(skip=self)


# ---- home strip chips
class TaskChip(QFrame):
    def __init__(self, win, task):
        super().__init__()
        self.win, self.tid = win, task["id"]
        self.setObjectName("chip")
        self.setProperty("hot", "true" if task.get("urgency", 1) >= 5 or due_soon(task.get("due"), 0) else "false")
        self.setFixedSize(330, 40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 0, 8, 0)
        h.setSpacing(8)
        cb = QCheckBox()
        cb.setToolTip("Mark done")
        cb.toggled.connect(lambda on: QTimer.singleShot(200, lambda: win.complete_task(self.tid)))
        meter = UrgencyMeter(task.get("urgency", 3), box=8, gap=2, interactive=False)
        title = ElidedLabel(task.get("text", ""))
        due = QLabel(due_text(task.get("due")))
        due.setObjectName("hot" if due_soon(task.get("due"), 0) else "dim")
        for w in (cb, meter):
            h.addWidget(w)
        h.addWidget(title, 1)
        h.addWidget(due)
        self.setToolTip(f"{task.get('text')}\nurgency {task.get('urgency')} ({URGENCY_NAMES.get(task.get('urgency'))})"
                        f"{' · ' + due_text(task.get('due')) if task.get('due') else ''}\n\nClick to open in TO-DO")
        self.search_key = task.get("text", "").lower()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.win.show_task(self.tid)


class ReminderChip(QFrame):
    def __init__(self, win, rem):
        super().__init__()
        self.win, self.day = win, parse_day(rem.get("date"))
        self.setObjectName("chip")
        self.setFixedSize(330, 40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 0, 8, 0)
        when = "today" if self.day == date.today() else "tomorrow"
        tag = QLabel("@")
        tag.setObjectName("hot")
        text = ElidedLabel((rem.get("time") + "  " if rem.get("time") else "") + rem.get("text", ""))
        lab = QLabel(when)
        lab.setObjectName("hot" if when == "today" else "dim")
        h.addWidget(tag)
        h.addWidget(text, 1)
        h.addWidget(lab)
        self.setToolTip(f"Reminder {when}\n\nClick to open in CALENDAR")
        self.search_key = rem.get("text", "").lower()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.day:
            self.win.show_day(self.day)


# ---- calendar
class DayCell(QFrame):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.day, self.in_month, self.lines, self.is_today, self.selected = None, True, [], False, False
        self.setMinimumSize(80, 64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_day(self, d, in_month, lines, is_today, selected):
        self.day, self.in_month, self.lines, self.is_today, self.selected = d, in_month, lines, is_today, selected
        self.setToolTip("\n".join(lines) if lines else "")
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        r = self.rect().adjusted(0, 0, -1, -1)
        p.fillRect(self.rect(), QColor("#000"))
        p.setPen(QPen(QColor("#fff" if self.selected else "#2a2a2a"), 2 if self.selected else 1))
        p.drawRect(r.adjusted(1, 1, -1, -1) if self.selected else r)
        f = mono_font(12, bold=self.is_today)
        p.setFont(f)
        fm = p.fontMetrics()
        num = str(self.day.day) if self.day else ""
        if self.is_today:
            w = fm.horizontalAdvance(num) + 8
            p.fillRect(QRectF(5, 4, w, fm.height() + 2), QColor("#fff"))
            p.setPen(QColor("#000"))
        else:
            p.setPen(QColor("#e6e6e6" if self.in_month else "#444"))
        p.drawText(QPointF(9, 4 + fm.ascent() + 1), num)
        p.setFont(mono_font(11))
        fm = p.fontMetrics()
        y = 8 + fm.height() * 2
        max_lines = max(0, int((self.height() - y) // fm.height()) + 1)
        lines = self.lines
        if len(lines) > max_lines and max_lines > 0:
            lines = lines[:max_lines - 1] + [f"+{len(self.lines) - max_lines + 1} more"]
        for ln in lines[:max_lines]:
            p.setPen(QColor("#bbb" if self.in_month else "#444"))
            p.drawText(QPointF(7, y), fm.elidedText(ln, Qt.TextElideMode.ElideRight, self.width() - 12))
            y += fm.height()
        p.end()

    def mousePressEvent(self, e):
        if self.day:
            self.page.select_day(self.day)

    def mouseDoubleClickEvent(self, e):
        if self.day:
            self.page.select_day(self.day)
            self.page.r_text.setFocus()


class CalendarPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        t = date.today()
        self.month = date(t.year, t.month, 1)
        self.sel = t
        h = QHBoxLayout(self)
        h.setContentsMargins(26, 22, 26, 10)
        h.setSpacing(16)
        left = QVBoxLayout()
        top = QHBoxLayout()
        prevb, nextb, todayb = QPushButton("‹"), QPushButton("›"), QPushButton("TODAY")
        prevb.clicked.connect(lambda: self.shift(-1))
        nextb.clicked.connect(lambda: self.shift(1))
        todayb.clicked.connect(lambda: self.goto(date.today()))
        self.title = QLabel()
        self.title.setObjectName("pageTitle")
        self.title.setMinimumWidth(210)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top.addWidget(prevb)
        top.addWidget(self.title)
        top.addWidget(nextb)
        top.addStretch(1)
        top.addWidget(todayb)
        left.addLayout(top)
        grid = QGridLayout()
        grid.setSpacing(3)
        for c, name in enumerate(WEEKDAYS):
            lab = QLabel(name)
            lab.setObjectName("dim")
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(lab, 0, c)
        self.cells = []
        for r in range(6):
            for c in range(7):
                cell = DayCell(self)
                grid.addWidget(cell, r + 1, c)
                self.cells.append(cell)
        for r in range(1, 7):
            grid.setRowStretch(r, 1)
        left.addLayout(grid, 1)
        hint = QLabel("Click a day to see it · double-click to add a reminder · "
                      "to-dos with a do-by date show up here automatically")
        hint.setObjectName("dim")
        hint.setWordWrap(True)
        left.addWidget(hint)
        h.addLayout(left, 1)

        side = QWidget()
        side.setFixedWidth(330)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        self.day_title = QLabel()
        self.day_title.setObjectName("pageTitle")
        self.day_title.setWordWrap(True)
        sv.addWidget(self.day_title)
        self.day_sub = QLabel()
        self.day_sub.setObjectName("dim")
        sv.addWidget(self.day_sub)
        sv.addSpacing(8)
        sv.addWidget(self._h("REMINDERS"))
        self.r_list = QListWidget()
        self.r_list.itemDoubleClicked.connect(self._edit_reminder)
        self.r_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.r_list.customContextMenuRequested.connect(self._reminder_menu)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.r_list, self._delete_reminder,
                  context=Qt.ShortcutContext.WidgetShortcut)
        sv.addWidget(self.r_list, 1)
        ra = QHBoxLayout()
        self.r_time = QLineEdit()
        self.r_time.setPlaceholderText("hh:mm")
        self.r_time.setFixedWidth(68)
        self.r_text = QLineEdit()
        self.r_text.setPlaceholderText("add a reminder… Enter")
        self.r_text.returnPressed.connect(self.add_reminder)
        self.r_time.returnPressed.connect(self.add_reminder)
        ra.addWidget(self.r_time)
        ra.addWidget(self.r_text, 1)
        sv.addLayout(ra)
        sv.addSpacing(10)
        sv.addWidget(self._h("TO-DOS DUE"))
        self.t_list = QListWidget()
        self.t_list.itemChanged.connect(self._task_toggled)
        self.t_list.itemDoubleClicked.connect(
            lambda it: it.data(Qt.ItemDataRole.UserRole) and self.win.show_task(it.data(Qt.ItemDataRole.UserRole)))
        sv.addWidget(self.t_list, 1)
        self.t_new = QLineEdit()
        self.t_new.setPlaceholderText("add a to-do due this day… Enter")
        self.t_new.returnPressed.connect(self.add_task)
        sv.addWidget(self.t_new)
        h.addWidget(side)
        self._filling = False
        self.refresh()

    @staticmethod
    def _h(text):
        lab = QLabel(text)
        lab.setObjectName("sectionHeader")
        return lab

    # ---- navigation
    def shift(self, months):
        y, m = self.month.year, self.month.month + months
        y += (m - 1) // 12
        m = (m - 1) % 12 + 1
        self.month = date(y, m, 1)
        self.refresh()

    def goto(self, d):
        self.month = date(d.year, d.month, 1)
        self.sel = d
        self.refresh()

    def select_day(self, d):
        if d.month != self.month.month or d.year != self.month.year:
            self.goto(d)
        else:
            self.sel = d
            self.refresh()

    # ---- data per day
    def _day_lines(self, d):
        iso = d.isoformat()
        st = self.win.store
        rems = sorted((r for r in st.reminders() if r.get("date") == iso), key=lambda r: r.get("time") or "99")
        tasks = [t for t in st.tasks() if t.get("due") == iso]
        lines = [f"* {r['time']} {r['text']}" if r.get("time") else f"* {r['text']}" for r in rems]
        lines += [f"[{'x' if t.get('done') else ' '}] {t.get('text')}" for t in
                  sorted(tasks, key=lambda t: (t.get("done", False), -t.get("urgency", 1)))]
        return lines

    def refresh(self):
        self.title.setText(self.month.strftime("%B %Y").upper())
        start = self.month - timedelta(days=self.month.weekday())
        today = date.today()
        for i, cell in enumerate(self.cells):
            d = start + timedelta(days=i)
            cell.set_day(d, d.month == self.month.month, self._day_lines(d), d == today, d == self.sel)
        self._fill_side()

    def _fill_side(self):
        d, st = self.sel, self.win.store
        iso = d.isoformat()
        self.day_title.setText(d.strftime("%A").upper())
        n = (d - date.today()).days
        rel = "today" if n == 0 else "tomorrow" if n == 1 else "yesterday" if n == -1 else \
            (f"in {n} days" if n > 0 else f"{-n} days ago")
        self.day_sub.setText(f"{d.day} {d:%B %Y} · {rel}")
        self.r_list.clear()
        for r in sorted((r for r in st.reminders() if r.get("date") == iso), key=lambda r: r.get("time") or "99"):
            it = QListWidgetItem((f"{r['time']}   " if r.get("time") else "") + r.get("text", ""))
            it.setData(Qt.ItemDataRole.UserRole, r["id"])
            self.r_list.addItem(it)
        if not self.r_list.count():
            it = QListWidgetItem("no reminders")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            it.setForeground(QColor("#555"))
            self.r_list.addItem(it)
        self._filling = True
        self.t_list.clear()
        tasks = sorted((t for t in st.tasks() if t.get("due") == iso),
                       key=lambda t: (t.get("done", False), -t.get("urgency", 1)))
        for t in tasks:
            it = QListWidgetItem(f"{'#' * t.get('urgency', 1):<5}  {t.get('text', '')}")
            it.setData(Qt.ItemDataRole.UserRole, t["id"])
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if t.get("done") else Qt.CheckState.Unchecked)
            it.setToolTip(f"urgency {t.get('urgency')} · double-click to open in TO-DO")
            if t.get("done"):
                it.setForeground(QColor("#666"))
            self.t_list.addItem(it)
        if not tasks:
            it = QListWidgetItem("nothing due")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            it.setForeground(QColor("#555"))
            self.t_list.addItem(it)
        self._filling = False

    # ---- reminders
    def add_reminder(self):
        text = self.r_text.text().strip()
        if not text:
            self.r_text.setFocus()
            return
        tm = norm_time(self.r_time.text())
        if tm is None:
            self.win.flash("Time should look like 14:30. Leave it blank for no time.")
            self.r_time.setFocus()
            return
        self.win.store.add_reminder(self.sel.isoformat(), text, tm)
        self.r_text.clear()
        self.r_time.clear()
        self.refresh()
        self.win.tasks_changed(skip=self)

    def _rid(self, it):
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def _edit_reminder(self, it):
        rid = self._rid(it)
        r = self.win.store.get_reminder(rid)
        if not r:
            return
        text, ok = QInputDialog.getText(self, "Edit reminder", "Reminder:", text=r.get("text", ""))
        if not ok or not text.strip():
            return
        tm, ok = QInputDialog.getText(self, "Edit reminder", "Time (hh:mm, blank for none):", text=r.get("time", ""))
        if ok and norm_time(tm) is not None:
            r["time"] = norm_time(tm)
        r["text"] = text.strip()
        self.win.store.save()
        self.refresh()
        self.win.tasks_changed(skip=self)

    def _delete_reminder(self):
        rid = self._rid(self.r_list.currentItem())
        if rid:
            self.win.store.remove_reminder(rid)
            self.refresh()
            self.win.tasks_changed(skip=self)

    def _reminder_menu(self, pos):
        it = self.r_list.itemAt(pos)
        if not self._rid(it):
            return
        self.r_list.setCurrentItem(it)
        m = QMenu(self)
        m.addAction("Edit…", lambda: self._edit_reminder(it))
        m.addAction("Delete", self._delete_reminder)
        m.exec(self.r_list.mapToGlobal(pos))

    # ---- tasks
    def _task_toggled(self, it):
        if self._filling:
            return
        tid = it.data(Qt.ItemDataRole.UserRole)
        t = self.win.store.get_task(tid)
        if t:
            on = it.checkState() == Qt.CheckState.Checked
            t["done"], t["done_at"] = on, (now() if on else 0)
            self.win.store.save()
            QTimer.singleShot(0, self.refresh)
            self.win.tasks_changed(skip=self)

    def add_task(self):
        text = self.t_new.text().strip()
        if text:
            self.win.store.add_task(text, urgency=3, due=self.sel.isoformat())
            self.t_new.clear()
            self.refresh()
            self.win.tasks_changed(skip=self)


# ============================================================ dialogs
class StepDialog(QDialog):
    def __init__(self, parent, step=None):
        super().__init__(parent)
        self.setWindowTitle("Open step")
        self.setMinimumWidth(520)
        step = step or {}
        g = QGridLayout(self)
        self.target = QLineEdit(step.get("target", ""))
        self.target.setPlaceholderText("program, shortcut, file, folder, website or steam:// link")
        bf, bd = QPushButton("FILE…"), QPushButton("FOLDER…")
        bf.clicked.connect(lambda: self._browse(False))
        bd.clicked.connect(lambda: self._browse(True))
        self.args = QLineEdit(step.get("args", ""))
        self.args.setPlaceholderText("(optional) launch arguments")
        g.addWidget(QLabel("Open"), 0, 0)
        g.addWidget(self.target, 0, 1)
        g.addWidget(bf, 0, 2)
        g.addWidget(bd, 0, 3)
        g.addWidget(QLabel("Arguments"), 1, 0)
        g.addWidget(self.args, 1, 1, 1, 3)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        g.addWidget(bb, 2, 0, 1, 4)

    def _browse(self, folder):
        if folder:
            p = QFileDialog.getExistingDirectory(self, "Choose a folder")
        else:
            p, _ = QFileDialog.getOpenFileName(self, "Choose a program, shortcut or file",
                                               options=QFileDialog.Option.DontResolveSymlinks)
        if p:
            self.target.setText(QDir.toNativeSeparators(p))

    def value(self):
        return {"type": "open", "target": self.target.text().strip(), "args": self.args.text().strip()}


class ItemDialog(QDialog):
    def __init__(self, parent, item=None, category=None, for_project=False):
        super().__init__(parent)
        editing = bool(item and item.get("name"))
        self.setWindowTitle("Edit" if editing else "Add to Launchpad")
        self.setMinimumWidth(600)
        self.item = dict(item) if item else new_item(category=category or "apps")
        if category:
            self.item["category"] = category
        if not editing and self.item["category"] == "actions" and not self.item.get("target"):
            self.item["kind"] = "action"
        self._steps = [dict(s) for s in self.item.get("steps", [])]
        self._auto_name = not editing
        self._cat_touched = editing or bool(category)
        self.for_project = for_project

        v = QVBoxLayout(self)
        g = QGridLayout()
        self.name = QLineEdit(self.item.get("name", ""))
        self.name.setPlaceholderText("what to call it")
        self.name.textEdited.connect(lambda: setattr(self, "_auto_name", False))
        self.cat = QComboBox()
        for key, title in CATEGORIES:
            self.cat.addItem(title.title(), key)
        self.cat.setCurrentIndex(max(0, self.cat.findData(self.item.get("category"))))
        self.cat.activated.connect(lambda _: setattr(self, "_cat_touched", True))
        g.addWidget(QLabel("Name"), 0, 0)
        g.addWidget(self.name, 0, 1)
        self.cat_label = QLabel("Section")
        g.addWidget(self.cat_label, 1, 0)
        g.addWidget(self.cat, 1, 1)
        v.addLayout(g)

        kinds = QHBoxLayout()
        self.r_open = QRadioButton("Open one thing")
        self.r_action = QRadioButton("Action: several steps in order")
        kinds.addWidget(self.r_open)
        kinds.addWidget(self.r_action)
        kinds.addStretch(1)
        self.kinds_box = QWidget()
        self.kinds_box.setLayout(kinds)
        v.addWidget(self.kinds_box)

        self.pages = QStackedWidget()
        op = QWidget()
        og = QGridLayout(op)
        og.setContentsMargins(0, 0, 0, 0)
        self.target = QLineEdit(self.item.get("target", ""))
        self.target.setPlaceholderText("C:\\path\\to\\app.exe, a folder, a file, https://… or steam://…")
        self.target.editingFinished.connect(lambda: self._autofill(self.target.text().strip()))
        bf, bd = QPushButton("FILE…"), QPushButton("FOLDER…")
        bf.clicked.connect(lambda: self._browse(False))
        bd.clicked.connect(lambda: self._browse(True))
        self.args = QLineEdit(self.item.get("args", ""))
        self.args.setPlaceholderText("(optional) e.g. --launch-product=valorant --launch-patchline=live")
        self.workdir = QLineEdit(self.item.get("workdir", ""))
        self.workdir.setPlaceholderText("(optional) start-in folder")
        og.addWidget(QLabel("Target"), 0, 0)
        og.addWidget(self.target, 0, 1)
        og.addWidget(bf, 0, 2)
        og.addWidget(bd, 0, 3)
        og.addWidget(QLabel("Arguments"), 1, 0)
        og.addWidget(self.args, 1, 1, 1, 3)
        og.addWidget(QLabel("Start in"), 2, 0)
        og.addWidget(self.workdir, 2, 1, 1, 3)
        tip = QLabel("Tip: you can also drag apps, shortcuts, Steam game shortcuts, folders, files "
                     "or links from your browser straight onto Launchpad.")
        tip.setObjectName("dim")
        tip.setWordWrap(True)
        og.addWidget(tip, 3, 0, 1, 4)
        self.pages.addWidget(op)

        ap = QWidget()
        av = QVBoxLayout(ap)
        av.setContentsMargins(0, 0, 0, 0)
        self.steps = QListWidget()
        self.steps.itemDoubleClicked.connect(lambda _: self._edit_step())
        av.addWidget(self.steps, 1)
        row = QHBoxLayout()
        for text, slot in (("+ OPEN", self._add_open), ("+ WAIT", self._add_wait), ("EDIT", self._edit_step),
                           ("UP", lambda: self._shift(-1)), ("DOWN", lambda: self._shift(1)),
                           ("REMOVE", self._remove_step)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        av.addLayout(row)
        vpn = QHBoxLayout()
        vb = QPushButton("+ SURFSHARK VPN STEP")
        vb.clicked.connect(self._add_surfshark)
        vpn.addWidget(vb)
        vpn.addStretch(1)
        av.addLayout(vpn)
        atip = QLabel("Steps run top to bottom. Add a WAIT after slow apps (like a VPN) before the next step. "
                      "For one-click VPN: in Surfshark's own settings, turn on auto-connect so opening it connects you.")
        atip.setObjectName("dim")
        atip.setWordWrap(True)
        av.addWidget(atip)
        self.pages.addWidget(ap)
        v.addWidget(self.pages, 1)

        self.r_open.toggled.connect(lambda on: self.pages.setCurrentIndex(0 if on else 1))
        (self.r_action if self.item.get("kind") == "action" else self.r_open).setChecked(True)
        self.pages.setCurrentIndex(1 if self.item.get("kind") == "action" else 0)
        if for_project:
            self.cat.hide()
            self.cat_label.hide()
            self.kinds_box.hide()
            self.r_open.setChecked(True)
        self._refresh_steps()

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        if self.item.get("target") and self._auto_name and not self.item.get("name"):
            self._autofill(self.item["target"])

    # open page
    def _browse(self, folder):
        if folder:
            p = QFileDialog.getExistingDirectory(self, "Choose a folder")
        else:
            p, _ = QFileDialog.getOpenFileName(self, "Choose a program, shortcut or file",
                                               options=QFileDialog.Option.DontResolveSymlinks)
        if p:
            p = QDir.toNativeSeparators(p)
            self.target.setText(p)
            self._autofill(p)

    def _autofill(self, t):
        if not t:
            return
        guess = item_from_url(t) if is_url(t) else item_from_path(t)
        if self._auto_name and guess["name"] and guess["name"] != "Game":
            self.name.setText(guess["name"])
        if not self._cat_touched:
            self.cat.setCurrentIndex(max(0, self.cat.findData(guess["category"])))

    # action page
    def _refresh_steps(self):
        self.steps.clear()
        for s in self._steps:
            if s.get("type") == "wait":
                self.steps.addItem(f"WAIT  {s.get('seconds', 1)} s")
            else:
                extra = f"  {s['args']}" if s.get("args") else ""
                self.steps.addItem(f"OPEN  {s.get('target', '')}{extra}")

    def _add_open(self):
        d = StepDialog(self)
        if d.exec() and d.value()["target"]:
            self._steps.append(d.value())
            self._refresh_steps()

    def _add_wait(self):
        secs, ok = QInputDialog.getDouble(self, "Wait", "Seconds to wait:", 5, 0.5, 120, 1)
        if ok:
            self._steps.append({"type": "wait", "seconds": secs})
            self._refresh_steps()

    def _add_surfshark(self):
        path = find_surfshark()
        if not path:
            QMessageBox.information(self, "Surfshark", "I couldn't find Surfshark.exe in the usual places. Point me to it.")
            path, _ = QFileDialog.getOpenFileName(self, "Find Surfshark.exe", filter="Programs (*.exe)")
            path = QDir.toNativeSeparators(path) if path else ""
        if path:
            self._steps.append({"type": "open", "target": path, "args": ""})
            if self._auto_name and not self.name.text():
                self.name.setText("VPN ON (Surfshark)")
            self._refresh_steps()

    def _edit_step(self):
        r = self.steps.currentRow()
        if r < 0:
            return
        s = self._steps[r]
        if s.get("type") == "wait":
            secs, ok = QInputDialog.getDouble(self, "Wait", "Seconds to wait:", float(s.get("seconds", 5)), 0.5, 120, 1)
            if ok:
                s["seconds"] = secs
        else:
            d = StepDialog(self, s)
            if d.exec() and d.value()["target"]:
                self._steps[r] = d.value()
        self._refresh_steps()
        self.steps.setCurrentRow(r)

    def _shift(self, delta):
        r = self.steps.currentRow()
        n = r + delta
        if 0 <= r < len(self._steps) and 0 <= n < len(self._steps):
            self._steps[r], self._steps[n] = self._steps[n], self._steps[r]
            self._refresh_steps()
            self.steps.setCurrentRow(n)

    def _remove_step(self):
        r = self.steps.currentRow()
        if r >= 0:
            del self._steps[r]
            self._refresh_steps()

    def _accept(self):
        is_action = self.r_action.isChecked() and not self.for_project
        cat = self.cat.currentData()
        name = self.name.text().strip()
        if is_action:
            if not self._steps:
                QMessageBox.warning(self, "Action", "Add at least one step.")
                return
            self.item.update(kind="action", steps=self._steps, target="", args="", workdir="")
            name = name or "New action"
        else:
            t = self.target.text().strip().strip('"')
            if not t:
                QMessageBox.warning(self, "Target", "Choose what this should open.")
                return
            if (cat == "links" and not is_url(t) and "." in t and not re.match(r"^[A-Za-z]:", t)
                    and not t.startswith("\\\\")):
                t = "https://" + t
            if not name:
                g = item_from_url(t) if is_url(t) else item_from_path(t)
                name = g["name"]
            self.item.update(kind="open", target=t, args=self.args.text().strip(),
                             workdir=self.workdir.text().strip(), steps=[])
        self.item["name"] = name
        if not self.for_project:
            self.item["category"] = cat
        self.accept()


# ============================================================ settings
class SettingsPage(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        s = win.store.settings
        v = QVBoxLayout(self)
        v.setContentsMargins(26, 22, 26, 16)
        v.setSpacing(12)
        title = QLabel("SETTINGS")
        title.setObjectName("pageTitle")
        v.addWidget(title)

        v.addWidget(self._h("HOTKEY"))
        row = QHBoxLayout()
        self.hk = QKeySequenceEdit(QKeySequence(s["hotkey"]))
        try:
            self.hk.setMaximumSequenceLength(1)
        except AttributeError:
            pass
        self.hk.setFixedWidth(240)
        apply = QPushButton("APPLY")
        apply.clicked.connect(self.apply_hotkey)
        self.hk_status = QLabel()
        self.hk_status.setObjectName("dim")
        row.addWidget(self.hk)
        row.addWidget(apply)
        row.addWidget(self.hk_status, 1)
        v.addLayout(row)

        v.addWidget(self._h("BEHAVIOUR"))
        self.cb_start = QCheckBox("Start with Windows, waiting in the tray (keeps the hotkey working after a restart)")
        self.cb_start.setChecked(s["start_with_windows"])
        self.cb_start.toggled.connect(self._start_toggled)
        self.cb_tray = QCheckBox("Closing the window keeps Launchpad running in the tray")
        self.cb_tray.setChecked(s["close_to_tray"])
        self.cb_tray.toggled.connect(lambda on: self._set("close_to_tray", on))
        self.cb_hide = QCheckBox("Hide Launchpad after opening something")
        self.cb_hide.setChecked(s["hide_after_launch"])
        self.cb_hide.toggled.connect(lambda on: self._set("hide_after_launch", on))
        for cb in (self.cb_start, self.cb_tray, self.cb_hide):
            v.addWidget(cb)

        v.addWidget(self._h("ART"))
        arthint = QLabel("Pick the art, its size, and a different art for when the window isn't maximised "
                         "from the ART \u25be button on the art itself.")
        arthint.setObjectName("dim")
        arthint.setWordWrap(True)
        v.addWidget(arthint)
        arow = QHBoxLayout()
        self.cb_anim = QCheckBox("Animate")
        self.cb_anim.setChecked(s["animation"])
        self.cb_anim.toggled.connect(self._anim_changed)
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(0, 2)
        self.speed.setValue(s.get("anim_speed", 1))
        self.speed.setFixedWidth(140)
        self.speed.valueChanged.connect(self._anim_changed)
        arow.addWidget(self.cb_anim)
        arow.addSpacing(20)
        arow.addWidget(QLabel("slow"))
        arow.addWidget(self.speed)
        arow.addWidget(QLabel("fast"))
        arow.addStretch(1)
        v.addLayout(arow)

        v.addWidget(self._h("FILES"))
        brow = QHBoxLayout()
        for text, slot in (("CREATE DESKTOP SHORTCUT", self._shortcut), ("OPEN DATA FOLDER", self._open_data),
                           ("EXPORT BACKUP…", self._export), ("IMPORT BACKUP…", self._import)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            brow.addWidget(b)
        brow.addStretch(1)
        v.addLayout(brow)
        info = QLabel(f"Launchpad v{VERSION} \u00b7 everything is saved to {win.store.path}")
        info.setObjectName("dim")
        info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(info)
        v.addStretch(1)

    @staticmethod
    def _h(text):
        lab = QLabel("── " + text + " " + "─" * 200)
        lab.setObjectName("sectionHeader")
        lab.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        return lab

    def _set(self, key, val):
        self.win.store.settings[key] = val
        self.win.store.save()

    def _start_toggled(self, on):
        self._set("start_with_windows", on)
        ok = set_autostart(on)
        self.win.flash("Will start with Windows" if on and ok else "Won't start with Windows" if ok else
                       "Couldn't change the startup setting")

    def _anim_changed(self, *_):
        self._set("animation", self.cb_anim.isChecked())
        self._set("anim_speed", self.speed.value())
        self.win.home.banner.apply_settings()

    def apply_hotkey(self):
        seq = self.hk.keySequence().toString(QKeySequence.SequenceFormat.PortableText).split(",")[0].strip()
        if not seq:
            return
        ok, msg = self.win.hotkeys.register(seq)
        if ok:
            self._set("hotkey", seq)
            self.win.update_hotkey_labels()
        else:
            self.win.hotkeys.register(self.win.store.settings["hotkey"])
        self.hk_status.setText(msg)

    def _shortcut(self):
        ok, msg = create_desktop_shortcut()
        self.win.flash(msg)

    def _open_data(self):
        Launcher.open_target(str(self.win.store.path.parent))

    def _export(self):
        p, _ = QFileDialog.getSaveFileName(self, "Export backup", f"launchpad-backup-{datetime.now():%Y%m%d}.json",
                                           "JSON (*.json)")
        if p:
            Path(p).write_text(json.dumps(self.win.store.data, indent=2), encoding="utf-8")
            self.win.flash(f"Backup saved to {p}")

    def _import(self):
        p, _ = QFileDialog.getOpenFileName(self, "Import backup", filter="JSON (*.json)")
        if not p:
            return
        try:
            d = json.loads(Path(p).read_text(encoding="utf-8"))
            assert isinstance(d.get("items"), list) and isinstance(d.get("projects"), list)
        except Exception:  # noqa: BLE001
            QMessageBox.warning(self, "Import", "That doesn't look like a Launchpad backup.")
            return
        if QMessageBox.question(self, "Import", "Replace everything in Launchpad with this backup?") \
                == QMessageBox.StandardButton.Yes:
            self.win.store.data["items"] = d["items"]
            self.win.store.data["projects"] = d["projects"]
            self.win.store.data["pins"] = list(d.get("pins", []))
            self.win.store.data["tasks"] = list(d.get("tasks", []))
            self.win.store.data["reminders"] = list(d.get("reminders", []))
            self.win.store.save()
            self.win.refresh_all()
            self.win.flash("Backup imported")


# ============================================================ main window
QSS = """
QWidget { background: #000; color: #e6e6e6; }
QFrame#sidebar { border-right: 1px solid #262626; }
QLabel#logo { color: #fff; padding: 20px 16px 2px 16px; }
QLabel#tagline { color: #777; padding: 0 16px 16px 16px; }
QLabel#dim { color: #777; }
QLabel#sectionHeader { color: #fff; font-weight: bold; }
QPushButton#sectionToggle { text-align: left; border: none; padding: 0; color: #fff; font-weight: bold; background: transparent; }
QPushButton#sectionToggle:hover { color: #fff; background: #141414; }
QToolButton#artBtn { color: #666; background: #000; border: 1px solid #2a2a2a; padding: 2px 8px; }
QToolButton#artBtn:hover { color: #000; background: #fff; border-color: #fff; }
QListWidget#pinnedList::item { padding: 6px 4px; border-bottom: 1px solid #1a1a1a; }
QListWidget#taskList::item { border-bottom: 1px solid #1a1a1a; }
QListWidget#taskList::item:selected { background: #1e1e1e; color: #fff; border-left: 2px solid #fff; }
QFrame#chip { border: 1px solid #3a3a3a; }
QFrame#chip QLabel, QFrame#chip QCheckBox { background: transparent; }
QWidget#taskRow, QWidget#taskRow QLabel, QWidget#taskRow QCheckBox { background: transparent; }
QFrame#chip:hover { border-color: #fff; background: #141414; }
QFrame#chip[hot="true"] { border: 1px solid #bbb; }
QLabel#hot { color: #fff; font-weight: bold; }
QDateEdit { background: #000; color: #eee; border: 1px solid #4a4a4a; padding: 5px; }
QDateEdit:disabled { color: #555; border-color: #2a2a2a; }
QDateEdit::drop-down { border: none; width: 16px; }
QCalendarWidget QWidget { background: #000; color: #e6e6e6; alternate-background-color: #000; }
QCalendarWidget QToolButton { color: #fff; background: #000; border: none; padding: 4px 8px; }
QCalendarWidget QToolButton:hover { background: #fff; color: #000; }
QCalendarWidget QAbstractItemView:enabled { color: #ddd; background: #000;
    selection-background-color: #fff; selection-color: #000; }
QCalendarWidget QAbstractItemView:disabled { color: #444; }
QCalendarWidget QSpinBox { background: #000; color: #fff; border: 1px solid #444; }
QListWidget::indicator { width: 11px; height: 11px; border: 1px solid #bbb; background: #000; }
QListWidget::indicator:checked { background: #777; border-color: #777; }
QListWidget#pinnedList::item:hover { background: #141414; }
QLabel#pageTitle { color: #fff; font-weight: bold; font-size: 18px; }
QFrame#section[drop="true"] { border: 1px dashed #fff; }
QPushButton { background: #000; color: #e6e6e6; border: 1px solid #777; padding: 6px 14px; }
QPushButton:hover { background: #fff; color: #000; border-color: #fff; }
QPushButton:pressed { background: #aaa; color: #000; }
QPushButton#nav { text-align: left; border: none; padding: 7px 16px; color: #aaa; }
QPushButton#nav:hover { color: #fff; background: #141414; }
QPushButton#nav:checked { background: #fff; color: #000; }
QPushButton#tile { text-align: left; padding: 0 8px; border: 1px solid #3a3a3a; }
QPushButton#tile:hover { background: #141414; color: #fff; border-color: #fff; }
QPushButton#tile:pressed { background: #2a2a2a; }
QPushButton#tile[missing="true"] { color: #666; text-decoration: line-through; border-style: dashed; }
QPushButton#addTile { border: 1px dashed #3a3a3a; color: #777; padding: 0 12px; }
QPushButton#addTile:hover { border-color: #fff; color: #fff; background: #141414; }
QPushButton#card { text-align: left; padding: 10px 12px; border: 1px solid #555; }
QPushButton#card:hover { background: #141414; color: #fff; border-color: #fff; }
QPushButton#card[done="true"] { color: #666; border-color: #2a2a2a; }
QLineEdit, QPlainTextEdit, QListWidget, QComboBox, QKeySequenceEdit, QDoubleSpinBox {
    background: #000; color: #eee; border: 1px solid #4a4a4a; padding: 5px;
    selection-background-color: #fff; selection-color: #000; }
QLineEdit:focus, QPlainTextEdit:focus, QListWidget:focus, QComboBox:focus { border: 1px solid #fff; }
QLineEdit#search { padding: 9px 10px; border: 1px solid #fff; }
QLineEdit#projName { font-size: 18px; font-weight: bold; border: none; border-bottom: 1px solid #4a4a4a; }
QListWidget::item { padding: 4px 2px; }
QListWidget::item:selected { background: #fff; color: #000; }
QComboBox::drop-down { border: none; width: 16px; }
QComboBox QAbstractItemView { background: #000; color: #eee; border: 1px solid #fff;
    selection-background-color: #fff; selection-color: #000; }
QScrollArea { border: none; }
QScrollBar:vertical { background: #000; width: 9px; margin: 0; }
QScrollBar::handle:vertical { background: #3a3a3a; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #fff; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QScrollBar:horizontal { height: 0; }
QMenu { background: #000; color: #eee; border: 1px solid #fff; padding: 4px; }
QMenu::item { padding: 5px 18px; }
QMenu::item:selected { background: #fff; color: #000; }
QMenu::item:disabled { color: #555; }
QMenu::separator { height: 1px; background: #333; margin: 4px 6px; }
QToolTip { background: #000; color: #fff; border: 1px solid #fff; padding: 4px; }
QCheckBox, QRadioButton { spacing: 8px; }
QCheckBox::indicator, QRadioButton::indicator { width: 11px; height: 11px; border: 1px solid #fff; background: #000; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked { background: #fff; }
QRadioButton::indicator { border-radius: 6px; }
QSplitter::handle { background: #1e1e1e; width: 1px; }
QStatusBar { color: #aaa; border-top: 1px solid #1e1e1e; }
QStatusBar::item { border: none; }
QSlider::groove:horizontal { height: 2px; background: #555; }
QSlider::handle:horizontal { background: #fff; width: 10px; margin: -6px 0; }
"""


def app_icon() -> QIcon:
    ico = resource_path("launchpad.ico")
    if ico.exists():
        return QIcon(str(ico))
    pm = QPixmap(64, 64)
    pm.fill(QColor("#000"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#fff"))
    pen.setWidth(4)
    p.setPen(pen)
    p.drawLine(4, 58, 60, 18)
    p.setBrush(QColor("#fff"))
    p.drawEllipse(QRectF(30, 10, 22, 22))
    p.end()
    return QIcon(pm)


class MainWindow(QMainWindow):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.home_dirty = False
        self._quitting = False
        self.counter = {"n": int(store.settings.get("ascents", 0))}
        self.arts = ArtManager(self.counter)
        self.launcher = Launcher()
        self.launcher.error.connect(self.flash)
        self.hotkeys = HotkeyManager()
        self.hotkeys.triggered.connect(self.toggle)

        self.setWindowTitle("LAUNCHPAD")
        self.setWindowIcon(app_icon())
        self.resize(1180, 840)
        self.setMinimumSize(920, 640)
        self.setAcceptDrops(True)

        central = QWidget()
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(176)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 1, 12)
        sv.setSpacing(2)
        logo = QLabel("LAUNCHPAD")
        logo.setObjectName("logo")
        logo.setFont(mono_font(17, True))
        tag = QLabel("keep it in sight")
        tag.setObjectName("tagline")
        sv.addWidget(logo)
        sv.addWidget(tag)

        self.stack = QStackedWidget()
        self.home = HomePage(self)
        self.projects = ProjectsPage(self)
        self.todo = TodoPage(self)
        self.calendar = CalendarPage(self)
        self.settings_page = SettingsPage(self)
        for page in (self.home, self.projects, self.todo, self.calendar, self.settings_page):
            self.stack.addWidget(page)

        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        self.nav_buttons = {}
        entries = [("home", "HOME")] + CATEGORIES + [("projects", "PROJECTS"), ("todo", "TO-DO"),
                                                     ("calendar", "CALENDAR"), ("settings", "SETTINGS")]
        for key, title in entries:
            b = QPushButton(("  " if key in CAT_NAMES else "") + title)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.go(k))
            self.nav.addButton(b)
            self.nav_buttons[key] = b
            if key == "actions":
                sv.addWidget(b)
                sv.addSpacing(10)
            else:
                sv.addWidget(b)
        sv.addStretch(1)
        addb = QPushButton("+ ADD")
        addb.setToolTip("Ctrl+N")
        addb.clicked.connect(lambda: self.add_item())
        wrap = QHBoxLayout()
        wrap.setContentsMargins(14, 0, 14, 0)
        wrap.addWidget(addb)
        sv.addLayout(wrap)
        self.hk_label = QLabel()
        self.hk_label.setObjectName("dim")
        self.hk_label.setWordWrap(True)
        self.hk_label.setContentsMargins(16, 8, 12, 0)
        sv.addWidget(self.hk_label)

        h.addWidget(side)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.statusBar().setSizeGripEnabled(False)

        QShortcut(QKeySequence("Ctrl+N"), self, lambda: self.add_item())
        QShortcut(QKeySequence("Ctrl+F"), self, self._focus_search)
        QShortcut(QKeySequence("Ctrl+P"), self, lambda: self.go("projects"))
        QShortcut(QKeySequence("Ctrl+T"), self, lambda: (self.go("todo"), self.todo.new.setFocus()))
        QShortcut(QKeySequence("Ctrl+K"), self, lambda: self.go("calendar"))
        self._day = date.today()
        self.day_timer = QTimer(self)
        self.day_timer.timeout.connect(self._minute)
        self.day_timer.start(60_000)

        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(app_icon(), self)
            self.tray.setToolTip("Launchpad")
            m = QMenu()
            m.addAction("Open Launchpad", self.bring_up)
            m.addAction("Add something…", lambda: (self.bring_up(), self.add_item()))
            m.addSeparator()
            m.addAction("Quit", self.quit_app)
            self.tray.setContextMenu(m)
            self.tray.activated.connect(self._tray_click)
            self.tray.show()

        ok, msg = self.hotkeys.register(store.settings["hotkey"])
        if not ok and IS_WIN:
            QTimer.singleShot(1500, lambda: self.flash(f"Hotkey not set: {msg}"))
        self.update_hotkey_labels()
        if IS_WIN and store.settings.get("start_with_windows"):
            set_autostart(True)   # keeps the path current if the app moved
        self._first_run()
        self.refresh_all()
        self.go("home")

    # ---------------------------------------------------------- navigation
    def go(self, key):
        self.nav_buttons[key].setChecked(True)
        if key == "projects":
            self.projects.refresh_list() if self.projects.currentIndex() == 0 else None
            self.stack.setCurrentWidget(self.projects)
        elif key == "todo":
            self.todo.refresh()
            self.stack.setCurrentWidget(self.todo)
        elif key == "calendar":
            self.calendar.refresh()
            self.stack.setCurrentWidget(self.calendar)
        elif key == "settings":
            self.stack.setCurrentWidget(self.settings_page)
        else:
            if self.stack.currentWidget() is self.projects:
                self.projects.detail.flush()
            if self.home_dirty:
                self.home.refresh()
                self.home_dirty = False
            self.stack.setCurrentWidget(self.home)
            if key == "home":
                self.home.scroll.verticalScrollBar().setValue(0)
            else:
                self.home.scroll_to(key)

    def _focus_search(self):
        self.go("home")
        self.home.search.setFocus()
        self.home.search.selectAll()

    def update_hotkey_labels(self):
        hk = self.store.settings["hotkey"]
        self.hk_label.setText(f"{hk}\nshow / hide from anywhere" if IS_WIN else "hotkey: Windows only")
        self.home.search.setPlaceholderText(
            f"search everything…   Enter opens the top match   Esc clears   {hk} shows/hides")

    def refresh_all(self):
        self.home.refresh()
        self.home_dirty = False
        self.projects.refresh_list()

    # ---------------------------------------------------------- to-do / calendar glue
    def tasks_changed(self, skip=None):
        self.home.refresh_due()
        for page in (self.todo, self.calendar):
            if page is not skip and self.stack.currentWidget() is page:
                page.refresh()

    def show_task(self, tid):
        self.go("todo")
        self.todo.select(tid)

    def show_day(self, d):
        self.go("calendar")
        self.calendar.goto(d)

    def complete_task(self, tid):
        t = self.store.get_task(tid)
        if t and not t.get("done"):
            t["done"], t["done_at"] = True, now()
            self.store.save()
            self.flash(f"Done: {t.get('text')}")
            self.tasks_changed()

    def _minute(self):
        if date.today() != self._day:      # new day: "due soon" and "today" change
            self._day = date.today()
            self.tasks_changed()
            self.calendar.goto(self._day) if self.stack.currentWidget() is not self.calendar else None

    def flash(self, msg):
        self.statusBar().showMessage(msg, 6000)

    def _first_run(self):
        s = self.store.settings
        if not s.get("first_run"):
            return
        s["first_run"] = False
        path = find_surfshark() if IS_WIN else ""
        if path and not any(i.get("name") == "VPN ON (Surfshark)" for i in self.store.items()):
            self.store.data["items"].append(surfshark_action(path))
        self.store.save()

    # ---------------------------------------------------------- items
    def launch(self, item):
        self.launcher.run(item)
        stored = self.store.get_item(item["id"])
        if stored:
            stored["last_used"] = now()
            self.store.save()
            QTimer.singleShot(400, lambda: self.home.refresh_recent())
        self.flash(f"Opening {item.get('name')}…")
        if self.store.settings.get("hide_after_launch"):
            QTimer.singleShot(150, self.hide_window)

    def add_item(self, category=None, prefill=None, project_id=None, pin=False):
        d = ItemDialog(self, prefill, category=category, for_project=bool(project_id))
        style_titlebar(d)
        if not d.exec():
            return
        if project_id:
            p = self.store.get_project(project_id)
            if p:
                p.setdefault("items", []).append(d.item)
                p["updated"] = now()
                self.store.save()
                self.projects.detail.fill_pinned()
                self.home_dirty = True
            return
        self.store.add_item(d.item)
        if pin:
            self.store.pin(d.item["id"])
        self.home.refresh()
        self.flash(f"Added {d.item['name']} to {CAT_NAMES[d.item['category']].title()}"
                   + (" and pinned it" if pin else ""))

    def edit_item(self, item, project_id=None):
        d = ItemDialog(self, item, for_project=bool(project_id))
        style_titlebar(d)
        if not d.exec():
            return
        _icon_cache.pop(expand(d.item.get("target", "")), None)
        if project_id:
            p = self.store.get_project(project_id)
            if p:
                p["items"] = [d.item if i["id"] == d.item["id"] else i for i in p.get("items", [])]
                self.store.save()
                self.projects.detail.fill_pinned()
            return
        self.store.update_item(d.item)
        self.home.refresh()

    def remove_item(self, item):
        self.store.remove_item(item["id"])
        self.home.refresh()
        self.flash(f"Removed {item.get('name')}")

    def move_item(self, item, delta):
        self.store.move_item(item["id"], delta)
        self.home.refresh()

    def move_item_to(self, iid, cat, before_id=None):
        it = self.store.get_item(iid)
        if not it:
            return
        old = it.get("category")
        self.store.move_to(iid, cat, before_id)
        self.home.refresh()
        if old != cat:
            self.flash(f"Moved {it.get('name')} to {CAT_NAMES[cat].title()}")

    def pin_item(self, iid, before_id=None):
        it = self.store.get_item(iid)
        if it:
            self.store.pin(iid, before_id)
            self.home.refresh()

    def unpin_item(self, iid):
        self.store.unpin(iid)
        self.home.refresh()

    def set_category(self, item, cat):
        stored = self.store.get_item(item["id"])
        if stored:
            stored["category"] = cat
            self.store.save()
            self.home.refresh()

    def pin_to_project(self, item, pid):
        p = self.store.get_project(pid)
        if p:
            copy = dict(item, id=new_id(), last_used=0)
            p.setdefault("items", []).append(copy)
            p["updated"] = now()
            self.store.save()
            self.flash(f"Pinned {item.get('name')} to {p['name']}")

    def remove_project_item(self, pid, iid):
        p = self.store.get_project(pid)
        if p:
            p["items"] = [i for i in p.get("items", []) if i["id"] != iid]
            self.store.save()
            self.projects.detail.fill_pinned()

    # ---------------------------------------------------------- projects
    def new_project(self):
        name, ok = QInputDialog.getText(self, "New project", "Project name:")
        if ok and name.strip():
            p = self.store.add_project(name.strip())
            self.home_dirty = True
            self.go("projects")
            self.projects.open_project(p["id"])

    def show_project(self, pid):
        self.go("projects")
        self.projects.open_project(pid)

    # ---------------------------------------------------------- drag & drop
    @staticmethod
    def mime_ok(md):
        return md.hasUrls() or (md.hasText() and is_url(md.text().strip()))

    @staticmethod
    def candidates(md):
        out = []
        if md.hasUrls():
            for u in md.urls():
                if u.isLocalFile():
                    out.append(item_from_path(QDir.toNativeSeparators(u.toLocalFile())))
                elif u.toString():
                    out.append(item_from_url(u.toString()))
        elif md.hasText() and is_url(md.text().strip()):
            out.append(item_from_url(md.text().strip()))
        return out

    def handle_drop(self, md, category=None, project_id=None, pin=False):
        cands = self.candidates(md)
        if not cands:
            return
        if project_id:
            p = self.store.get_project(project_id)
            if p:
                p.setdefault("items", []).extend(cands)
                p["updated"] = now()
                self.store.save()
                self.projects.detail.fill_pinned()
                self.home_dirty = True
                self.flash(f"Pinned {len(cands)} item(s) to {p['name']}")
            return
        if category:
            for c in cands:
                c["category"] = category
                if category == "actions":
                    c["kind"] = "open"
        if len(cands) == 1:
            self.add_item(category=category, prefill=cands[0], pin=pin)
        else:
            for c in cands:
                self.store.data["items"].append(c)
                if pin:
                    self.store.data.setdefault("pins", []).append(c["id"])
            self.store.save()
            self.home.refresh()
            self.flash(f"Added {len(cands)} items")

    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md.hasFormat(MIME_ITEM):      # our own tile dropped somewhere that isn't a section
            e.ignore()
            return
        if self.mime_ok(md):
            e.acceptProposedAction()

    def dropEvent(self, e):
        if e.mimeData().hasFormat(MIME_ITEM):
            e.ignore()
            return
        on_project = (self.stack.currentWidget() is self.projects and self.projects.currentIndex() == 1)
        pid = self.projects.detail.pid if on_project else None
        md = e.mimeData()
        data = QMimeData()
        for fmt in md.formats():
            data.setData(fmt, md.data(fmt))
        e.acceptProposedAction()
        QTimer.singleShot(0, lambda: self.handle_drop(data, project_id=pid))

    # ---------------------------------------------------------- window / tray
    def showEvent(self, e):
        super().showEvent(e)
        style_titlebar(self)
        self.home.banner.choose()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.home.banner.set_window_height(self.height())

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == e.Type.WindowStateChange:
            QTimer.singleShot(0, self.home.banner.choose)

    def _tray_click(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.toggle()

    def toggle(self):
        if self.isVisible() and self.isActiveWindow() and not self.isMinimized():
            self.hide_window()
        else:
            self.bring_up()

    def bring_up(self):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        if IS_WIN:
            try:
                u = ctypes.windll.user32
                hwnd = int(self.winId())
                u.keybd_event(0x12, 0, 0, 0)       # Alt tap lets Windows hand over focus
                u.keybd_event(0x12, 0, 2, 0)
                u.ShowWindow(hwnd, 5)
                u.SetForegroundWindow(hwnd)
            except Exception:  # noqa: BLE001
                pass
        if self.stack.currentWidget() is self.home:
            self.home.search.setFocus()
            self.home.search.selectAll()

    def hide_window(self):
        if self.tray and self.store.settings.get("close_to_tray", True):
            self.projects.detail.flush()
            self.hide()
        else:
            self.showMinimized()

    def closeEvent(self, e):
        if not self._quitting and self.tray and self.store.settings.get("close_to_tray", True):
            e.ignore()
            self.projects.detail.flush()
            self.hide()
            if not self.store.settings.get("tray_tip_shown"):
                self.store.settings["tray_tip_shown"] = True
                self.store.save()
                self.tray.showMessage("Launchpad is still running",
                                      f"Press {self.store.settings['hotkey']} to bring it back. "
                                      "Quit from the tray icon.", app_icon(), 6000)
            return
        self.quit_app()
        e.accept()

    def quit_app(self):
        self._quitting = True
        self.projects.detail.flush()
        self.store.settings["ascents"] = self.counter["n"]
        self.store.save()
        self.hotkeys.unregister()
        if self.tray:
            self.tray.hide()
        QApplication.instance().quit()


# ============================================================ entry point
def main():
    if IS_WIN:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:  # noqa: BLE001
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    # already running? just bring that one up
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        return 0

    app.setFont(mono_font(13))
    app.setStyleSheet(QSS)
    store = Store(data_dir() / "launchpad.json")
    if "--install" in sys.argv:
        store.settings["start_with_windows"] = True
        store.save()
        create_desktop_shortcut()

    win = MainWindow(store)
    server = QLocalServer()
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)

    def on_conn():
        c = server.nextPendingConnection()
        if c:
            c.readyRead.connect(c.readAll)
            c.disconnected.connect(c.deleteLater)
        win.bring_up()
    server.newConnection.connect(on_conn)

    if "--tray" not in sys.argv or not win.tray:
        win.show()
    app.aboutToQuit.connect(lambda: (store.settings.__setitem__("ascents", win.counter["n"]), store.save()))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
