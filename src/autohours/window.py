"""Desktop geometry in the window's coordinate system, independent of font scaling."""

import sys


def initial_geometry(scale, work_area):
    """Return client size and centred position, leaving room for window chrome."""
    left, top, right, bottom = work_area
    available_width, available_height = right - left, bottom - top
    width = min(round(1040 * scale), max(1, available_width - round(32 * scale)))
    height = min(round(760 * scale), max(1, int(available_height * .85) - round(40 * scale)))
    return width, height, left + (available_width - width) // 2, top + (available_height - height) // 2


def windows_metrics(root):
    import ctypes
    from ctypes import wintypes

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                    ("work", wintypes.RECT), ("flags", wintypes.DWORD)]

    user32 = ctypes.windll.user32
    user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    user32.GetDpiForWindow.restype = wintypes.UINT
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    hwnd = root.winfo_id()
    dpi = user32.GetDpiForWindow(hwnd)
    info = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
    if not dpi or not user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(info)):
        raise OSError("Window metrics unavailable")
    rect = info.work
    return dpi / 96, (rect.left, rect.top, rect.right, rect.bottom)


def metrics(root):
    if sys.platform == "win32":
        try:
            scale, area = windows_metrics(root)
            # Tk may have cached a different font DPI. Normalize before fonts,
            # indicators or geometry are constructed, using this HWND's awareness.
            root.tk.call("tk", "scaling", scale * 96 / 72)
            return scale, area
        except (AttributeError, OSError):
            pass
    return max(1, float(root.tk.call("tk", "scaling")) / (96 / 72)), (
        0, 0, root.winfo_screenwidth(), root.winfo_screenheight())
