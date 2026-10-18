import sys

import pytest

from autohours import taskbar


def test_packaged_app_relaunches_itself_with_its_own_icon():
    assert taskbar.relaunch(True, "C:/Apps/autohours.exe") == ('"C:/Apps/autohours.exe"', "C:/Apps/autohours.exe,0")


def test_installed_app_relaunches_through_python_with_the_bundled_icon():
    command, icon = taskbar.relaunch(False, "C:/Python/python.exe")
    assert command == '"C:/Python/python.exe" -m autohours'
    path = icon.rsplit(",", 1)[0]
    assert icon.endswith(",0") and path.endswith("autohours.ico")
    assert open(path, "rb").read(4) == b"\0\0\1\0"


def test_app_id_is_set_after_the_relaunch_details():
    keys = [key for key, _ in taskbar.properties(True, "autohours.exe")]
    assert keys[-1] == taskbar.ID and set(keys) == {taskbar.RELAUNCH_COMMAND, taskbar.ICON_RESOURCE, taskbar.DISPLAY_NAME, taskbar.ID}


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_other_systems_are_left_alone(platform, monkeypatch):
    monkeypatch.setattr(taskbar, "_windows", lambda: pytest.fail("Windows-only code ran"))
    assert taskbar.label_windows(seconds=1, platform=platform) is None


def test_background_labelling_never_raises(monkeypatch):
    def broken():
        raise OSError("synthetic")
    monkeypatch.setattr(taskbar, "label_windows", broken)
    threads = []
    monkeypatch.setattr(taskbar.threading, "Thread", lambda target, daemon: threads.append(target) or type("T", (), {"start": lambda self: None})())
    taskbar.label_in_background()
    threads[0]()
