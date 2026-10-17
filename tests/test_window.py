from types import SimpleNamespace

import pytest

from autohours import window


def test_large_work_area_uses_logical_target_size():
    assert window.initial_geometry(1, (0, 0, 1920, 1040)) == (1040, 760, 440, 140)
    assert window.initial_geometry(1.5, (0, 0, 2560, 1600)) == (1560, 1140, 500, 230)


@pytest.mark.parametrize("scale,area", [
    (1, (0, 0, 1920, 1040)), (1.25, (0, 0, 1920, 1040)),
    (1.5, (0, 0, 2560, 1400)), (2.5, (0, 0, 3840, 2080)),
    (1.5, (0, 0, 1280, 680)), (1, (-1920, 40, 0, 1080)),
])
def test_initial_geometry_is_scaled_capped_and_centred(scale, area):
    width, height, x, y = window.initial_geometry(scale, area)
    left, top, right, bottom = area
    assert width <= min(round(1040 * scale), right - left)
    assert height <= round(760 * scale)
    assert height + round(40 * scale) <= (bottom - top) * .85
    assert abs((x - left) - (right - x - width)) <= 1
    assert abs((y - top) - (bottom - y - height)) <= 1
    assert window.initial_geometry(scale, area) == (width, height, x, y)


@pytest.mark.parametrize("cached_scaling", [96 / 72, 2, 4, 8])
def test_windows_dpi_overrides_cached_tk_scaling(monkeypatch, cached_scaling):
    calls = []
    root = SimpleNamespace(tk=SimpleNamespace(call=lambda *args: calls.append(args) or cached_scaling))
    monkeypatch.setattr(window.sys, "platform", "win32")
    monkeypatch.setattr(window, "windows_metrics", lambda _: (1.5, (0, 0, 1920, 1040)))
    scale, area = window.metrics(root)
    assert calls == [("tk", "scaling", 2.0)]
    assert window.initial_geometry(scale, area) == (1560, 824, 180, 108)
