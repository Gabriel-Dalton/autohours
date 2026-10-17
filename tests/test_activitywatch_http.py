from datetime import timedelta
import io
import json
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from autohours.activitywatch import ActivityWatch
from autohours.http import JsonHTTP, NoRedirect
from autohours.models import UserError, iso


class AWStub:
    def __init__(self, buckets, events=None):
        self.buckets = buckets
        self.events = events or []
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append(path)
        if path == "/buckets/":
            return self.buckets
        return self.events


def buckets(*hosts):
    return {f"aw-watcher-{kind}_{host}": {"hostname": host} for host in hosts for kind in ("window", "afk")}


def test_host_discovery_and_required_afk():
    assert "laptop" in ActivityWatch({"url": "http://localhost:5600"}, AWStub(buckets("laptop"))).check()
    with pytest.raises(UserError, match="hostname.*laptop.*workstation"):
        ActivityWatch({"url": "http://localhost:5600"}, AWStub(buckets("laptop", "workstation"))).check()
    with pytest.raises(UserError, match="AFK watcher"):
        ActivityWatch({"url": "http://localhost:5600"}, AWStub({"aw-watcher-window_laptop": {}})).check()


def test_web_buckets_stay_with_selected_host():
    data = buckets("laptop", "workstation")
    data.update({"aw-watcher-web-browser_laptop": {"hostname": "laptop"}, "aw-watcher-web-browser_workstation": {"hostname": "workstation"}})
    source = ActivityWatch({"url": "http://localhost:5600", "hostname": "laptop", "use_web": True}, AWStub(data))
    source.check()
    assert source.buckets[2] == ["aw-watcher-web-browser_laptop"]


def test_fetch_clips_crossing_events_and_unlimited_query(origin):
    stub = AWStub(buckets("laptop"), [{"timestamp": iso(origin - timedelta(minutes=5)), "duration": 1200, "data": {"title": "Acme"}}])
    source = ActivityWatch({"url": "http://localhost:5600"}, stub)
    data = source.fetch(origin, origin + timedelta(minutes=10))
    assert all(e.start == origin and e.end == origin + timedelta(minutes=10) for e in data.windows)
    queries = [parse_qs(urlsplit(path).query) for path in stub.calls[1:]]
    assert queries[0]["limit"] == ["-1"]
    assert queries[1]["limit"] == ["1"]
    assert "start" not in queries[1]


class Opener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []
    def open(self, request, timeout):
        self.requests.append(request)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return io.BytesIO(json.dumps(response).encode())


def test_429_backoff_then_success(monkeypatch):
    delays = []
    monkeypatch.setattr("autohours.http.time.sleep", delays.append)
    http = JsonHTTP("https://api.example", {"X-Api-Key": "fake-secret"})
    http.opener = Opener([HTTPError("https://api.example", 429, "rate limit", {"Retry-After": "1"}, None), {"ok": True}])
    assert http.request("GET", "/test") == {"ok": True}
    assert delays == [1]


def test_429_bounded_and_errors_hide_body(monkeypatch):
    monkeypatch.setattr("autohours.http.time.sleep", lambda delay: None)
    http = JsonHTTP("https://api.example")
    http.opener = Opener([HTTPError("https://api.example", 429, "private-body", {}, None) for _ in range(4)])
    with pytest.raises(UserError, match="HTTP 429") as error:
        http.request("POST", "/test", {"description": "Study"})
    assert "private-body" not in str(error.value)
    assert len(http.opener.requests) == 4


def test_network_failure_is_not_retried():
    http = JsonHTTP("https://api.example")
    http.opener = Opener([URLError("private-error")])
    with pytest.raises(UserError, match="preview again"):
        http.request("POST", "/test", {})
    assert len(http.opener.requests) == 1
    assert NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example") is None
