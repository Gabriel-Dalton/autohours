"""Give the browser app window autohours' own taskbar icon on Windows instead of the browser's."""

import sys
import threading
import time
from pathlib import Path

TITLE = "autohours"
APP_ID = "autohours.desktop"
APPMODEL = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"
PROPERTY_STORE = "{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}"
RELAUNCH_COMMAND, ICON_RESOURCE, DISPLAY_NAME, ID = 2, 3, 4, 5


def relaunch(frozen=None, executable=None):
    """Return the command and icon Windows uses for the window and when it is pinned."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    executable = sys.executable if executable is None else executable
    if frozen:
        return f'"{executable}"', f"{executable},0"
    icon = Path(__file__).resolve().parent / "web" / "autohours.ico"
    return f'"{executable}" -m autohours', f"{icon},0"


def properties(frozen=None, executable=None):
    command, icon = relaunch(frozen, executable)
    # The ID goes last so Windows reads the relaunch details with it.
    return [(RELAUNCH_COMMAND, command), (DISPLAY_NAME, TITLE), (ICON_RESOURCE, icon), (ID, APP_ID)]


def _label(hwnd, values):
    import ctypes
    import uuid
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]

        def __init__(self, text):
            value = uuid.UUID(text)
            super().__init__(value.time_low, value.time_mid, value.time_hi_version,
                             (ctypes.c_ubyte * 8)(*value.bytes[8:]))

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

    class PROPVARIANT(ctypes.Structure):
        _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                    ("r3", ctypes.c_ushort), ("value", ctypes.c_void_p), ("pad", ctypes.c_void_p)]

    store = ctypes.c_void_p()
    if ctypes.windll.shell32.SHGetPropertyStoreForWindow(
            wintypes.HWND(hwnd), ctypes.byref(GUID(PROPERTY_STORE)), ctypes.byref(store)):
        return
    table = ctypes.cast(ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    prototype = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))
    set_value, commit = prototype(table[6]), ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(table[7])
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(table[2])
    try:
        for pid, text in values:
            buffer = ctypes.create_unicode_buffer(text)
            variant = PROPVARIANT(vt=31, value=ctypes.cast(buffer, ctypes.c_void_p).value)  # VT_LPWSTR
            set_value(store, ctypes.byref(PROPERTYKEY(GUID(APPMODEL), pid)), ctypes.byref(variant))
        commit(store)
    finally:
        release(store)


def _windows():
    import ctypes
    from ctypes import wintypes
    user32, found = ctypes.windll.user32, []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        buffer = ctypes.create_unicode_buffer(64)
        user32.GetWindowTextW(hwnd, buffer, 64)
        if buffer.value == TITLE and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    return found


def label_windows(seconds=20, platform=None):
    """Watch briefly for the app window, whose title becomes the page title once it loads."""
    if (sys.platform if platform is None else platform) != "win32":
        return
    import ctypes
    ctypes.windll.ole32.CoInitialize(None)
    done, values, deadline = set(), properties(), time.monotonic() + seconds
    while time.monotonic() < deadline:
        for hwnd in set(_windows()) - done:
            done.add(hwnd)
            _label(hwnd, values)
        time.sleep(.25)


def label_in_background():
    def run():
        try:
            label_windows()
        except Exception:
            pass  # A generic taskbar icon is cosmetic; never interrupt the app.
    threading.Thread(target=run, daemon=True).start()
