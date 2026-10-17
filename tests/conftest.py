from datetime import datetime, timedelta, timezone
import re
import random

import pytest

from autohours.models import Activity, Event, Project


@pytest.fixture
def origin():
    return datetime(2026, 10, 16, 9, tzinfo=timezone.utc)


@pytest.fixture
def event(origin):
    def make(start, end, **data):
        return Event(origin + timedelta(minutes=start), origin + timedelta(minutes=end), data)
    return make


@pytest.fixture
def projects():
    return [Project("Acme Corp", "Acme Corp", "Project work", True, {"title": [re.compile("acme", re.I)]}),
            Project("Learning", "Learning", "Study", False, {"title": [re.compile("course", re.I)], "app": [re.compile("StudyApp", re.I)]})]


@pytest.fixture
def settings():
    return {"merge_gap_minutes": 5, "min_block_minutes": 10, "round_to_minutes": 0}


@pytest.fixture
def switching_activity(origin):
    """Synthetic work with rapid switches, changing titles and explicit AFK."""
    def make(hours=1, seed=1729):
        rng = random.Random(seed)
        windows, afk = [], []
        cursor = 0
        index = 0
        kinds = ("editor", "chat", "editor", "browser", "away")
        while cursor < hours * 3600:
            kind = kinds[index % len(kinds)]
            remaining = hours * 3600 - cursor
            maximum = 30 if kind == "chat" else 20 if kind == "away" else 90
            if remaining > 90:
                maximum = min(maximum, remaining - 5)
            seconds = rng.randint(5, min(maximum, remaining))
            if 0 < remaining - seconds < 5:
                seconds = remaining
            a, b = origin + timedelta(seconds=cursor), origin + timedelta(seconds=cursor + seconds)
            app, title = {"editor": ("Editor", "Acme file"), "chat": ("Chat", "Private chat"),
                          "browser": ("Browser", "course tab"), "away": ("Editor", "Acme idle")}[kind]
            windows.append(Event(a, b, {"app": app, "title": f"{title} {index}"}))
            afk.append(Event(a, b, {"status": "afk" if kind == "away" else "not-afk"}))
            cursor += seconds
            index += 1
        return Activity(windows, afk)
    return make


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import socket
    from autohours import credentials

    def forbidden(*args, **kwargs):
        raise AssertionError("Tests must not access the network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.delenv("CLOCKIFY_API_KEY", raising=False)
    monkeypatch.setattr(credentials, "windows_key", lambda: "")


@pytest.fixture(autouse=True)
def private_test_config(tmp_path, monkeypatch):
    from autohours import credentials
    monkeypatch.setattr(credentials, "credential_path", lambda: tmp_path / "credentials")
