from datetime import datetime, timedelta, timezone
import re

import pytest

from autohours.models import Event, Project


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


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("Tests must not access the network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
