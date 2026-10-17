import struct
import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("tkinter")
from autohours import theme
from test_desktop import hidden_root


def contrast(first, second):
    def luminance(value):
        channels = [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
        return sum(c * weight for c, weight in zip(linear, (.2126, .7152, .0722)))
    low, high = sorted((luminance(first), luminance(second)))
    return (high + .05) / (low + .05)


@pytest.mark.parametrize("palette", [theme.LIGHT, theme.DARK])
def test_secondary_border_contrast(palette):
    for background in ("card", "page"):
        assert contrast(palette["secondary_border"], palette[background]) >= 3


@pytest.mark.parametrize("dark", [False, True])
def test_filled_indicators_and_visible_rings(hidden_root, dark):
    palette = theme.apply(hidden_root, dark=dark)
    for background in ("card", "stripe", "page"):
        assert contrast(palette["accent_text"], palette[background]) >= 3
    images = hidden_root._indicator_images
    def rgb(color):
        return tuple(bytes.fromhex(color[1:]))
    for off, on in (images[:2], images[2:]):
        middle = off.width() // 2
        assert off.get(middle, middle) == rgb(palette["card"])
        assert on.get(middle, middle) == rgb(palette["accent_text"])
        assert off.get(middle, 2) == on.get(middle, 2) == rgb(palette["accent_text"])
    style = theme.ttk.Style(hidden_root)
    for name in ("TCheckbutton", "TRadiobutton"):
        assert "Autohours" in str(style.layout(name))


@pytest.mark.parametrize("palette", [theme.LIGHT, theme.DARK])
def test_palette_contrast_for_text_states_and_focus(palette):
    for background in ("page", "card", "stripe", "selected"):
        for foreground in ("text", "muted", "accent_text", "success", "warning", "danger"):
            assert contrast(palette[foreground], palette[background]) >= 4.5, (foreground, background)
        assert contrast(palette["focus"], palette[background]) >= 3
    for background in ("accent", "accent_hover", "accent_pressed"):
        assert contrast(palette["on_accent"], palette[background]) >= 4.5
    assert contrast(palette["accent"], "#ffffff") >= 4.5
    assert contrast(palette["indicator_mark"], palette["accent_text"]) >= 4.5


@pytest.mark.parametrize("setting, expected", [(0, True), (1, False)])
def test_windows_appearance(monkeypatch, setting, expected):
    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass
    monkeypatch.setattr(theme.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "winreg", SimpleNamespace(HKEY_CURRENT_USER=1,
        OpenKey=lambda *_: Key(), QueryValueEx=lambda *_: (setting, 4)))
    assert theme.system_dark() is expected


@pytest.mark.parametrize("output, code, expected", [("Dark\n", 0, True), ("", 1, False), ("Light", 0, False)])
def test_macos_appearance(monkeypatch, output, code, expected):
    monkeypatch.setattr(theme.sys, "platform", "darwin")
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout=output, returncode=code)
    monkeypatch.setattr(theme.subprocess, "run", run)
    assert theme.system_dark() is expected
    assert calls[0][0] == ["defaults", "read", "-g", "AppleInterfaceStyle"]
    assert calls[0][1]["timeout"] == 2


def test_appearance_fallback(monkeypatch):
    monkeypatch.setattr(theme.sys, "platform", "linux")
    assert theme.system_dark() is False
    monkeypatch.setattr(theme.sys, "platform", "darwin")
    def unavailable(*args, **kwargs):
        raise OSError("unavailable")
    monkeypatch.setattr(theme.subprocess, "run", unavailable)
    assert theme.system_dark() is False


def test_packaged_icons_are_reproducible(tmp_path):
    import runpy
    from pathlib import Path
    packaging = Path(__file__).resolve().parents[1] / "packaging"
    generator = runpy.run_path(str(packaging / "generate_icons.py"))
    generator["generate"](tmp_path)
    for name in ("autohours.ico", "autohours.icns"):
        assert (tmp_path / name).read_bytes() == (packaging / name).read_bytes()
    data = (tmp_path / "autohours.ico").read_bytes()
    assert struct.unpack("<HHH", data[:6]) == (0, 1, 6)
    for index in range(6):
        width, height, _, _, _, depth, length, offset = struct.unpack("<BBBBHHII", data[6 + index * 16:22 + index * 16])
        assert width == height and depth == 32
        assert data[offset:offset + 8] == b"\x89PNG\r\n\x1a\n"
        assert offset + length <= len(data)
