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


@pytest.mark.parametrize("ipv4_available", [True, False])
def test_localhost_prefers_ipv4_and_preserves_ipv6_fallback(monkeypatch, ipv4_available):
    from http.client import HTTPConnection
    from autohours.http import LocalConnection, LocalHTTPHandler
    hosts = []
    def connect(connection):
        hosts.append(connection.host)
        if connection.host == "127.0.0.1" and not ipv4_available:
            raise ConnectionRefusedError()
    monkeypatch.setattr(HTTPConnection, "connect", connect)
    connection = LocalConnection("localhost", 5600)
    connection.connect()
    assert hosts == (["127.0.0.1"] if ipv4_available else ["127.0.0.1", "::1"])
    assert connection.host == "localhost"
    assert any(isinstance(handler, LocalHTTPHandler) for handler in JsonHTTP("http://localhost:5600", local=True).opener.handlers)
    assert not any(isinstance(handler, LocalHTTPHandler) for handler in JsonHTTP("https://api.example").opener.handlers)


def test_explicit_hosts_are_not_rewritten(monkeypatch):
    from http.client import HTTPConnection
    from autohours.http import LocalConnection
    hosts = []
    monkeypatch.setattr(HTTPConnection, "connect", lambda connection: hosts.append(connection.host))
    for host in ("::1", "127.0.0.1", "service.example"):
        LocalConnection(host, 5600).connect()
    assert hosts == ["::1", "127.0.0.1", "service.example"]


def test_session_cache_batches_history_expires_and_does_not_cache_today(monkeypatch):
    from datetime import datetime, timezone
    from autohours import activitywatch
    from test_setup import Clock
    monkeypatch.setattr(activitywatch, "datetime", Clock)
    ticks = [0]
    monkeypatch.setattr(activitywatch, "monotonic", lambda: ticks[0])
    stub = AWStub(buckets("laptop"), [{"timestamp": "2026-10-15T23:00:00Z", "duration": 7200, "data": {"title": "Example"}}])
    source = activitywatch.SessionActivityWatch({"url": "http://localhost:5600"}, timezone.utc, stub)
    start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    end = datetime(2026, 10, 17, tzinfo=timezone.utc)
    source.fetch(start, end)
    assert len(stub.calls) == 5  # A month is fetched together, not one call per day.
    day = end - timedelta(days=1)
    cached = source.fetch(day, end)
    assert len(stub.calls) == 5 and cached.windows
    cached.windows[0].data["title"] = "Changed outside the cache"
    assert source.fetch(day, end).windows[0].data["title"] == "Example"
    source.fetch(end, Clock.now(timezone.utc))
    source.fetch(end, Clock.now(timezone.utc))
    assert len(stub.calls) == 13
    ticks[0] = 31
    source.check()
    assert len(stub.calls) == 14  # Discovery refreshes independently.
    ticks[0] = 301
    source.fetch(day, end)
    assert len(stub.calls) == 19  # Expired discovery and events are fetched again.


def test_cached_days_use_local_midnights_including_dst(monkeypatch):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    from autohours import activitywatch
    stub = AWStub(buckets("laptop"))
    source = activitywatch.SessionActivityWatch({"url": "http://localhost:5600"}, ZoneInfo("America/Vancouver"), stub)
    # This completed local day had 23 hours.
    start = datetime(2026, 3, 8, 8, tzinfo=timezone.utc)
    end = datetime(2026, 3, 9, 7, tzinfo=timezone.utc)
    source.fetch(start, end)
    assert list(source.days) == [(start, end)]
    source.fetch(start, end)
    assert len(stub.calls) == 5


def test_changed_bucket_selection_discards_cached_events(monkeypatch, origin):
    from datetime import timezone
    from autohours import activitywatch
    stub = AWStub(buckets("laptop"))
    source = activitywatch.SessionActivityWatch({"url": "http://localhost:5600"}, timezone.utc, stub)
    source.fetch(origin, origin + timedelta(hours=1))
    assert source.days
    source.check(buckets("desktop"))
    assert not source.days
    assert source.buckets[0] == "aw-watcher-window_desktop"
