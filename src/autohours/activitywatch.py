from datetime import timedelta
from urllib.parse import quote, urlencode

from .http import JsonHTTP
from .models import Activity, Event, UserError, iso, timestamp


class ActivityWatch:
    def __init__(self, settings, http=None):
        base = settings["url"].rstrip("/")
        if not base.endswith("/api/0"):
            base += "/api/0"
        self.http = http or JsonHTTP(base, label="ActivityWatch", local=True)
        self.settings = settings
        self.buckets = None

    def check(self, buckets=None):
        if buckets is None:
            buckets = self.http.request("GET", "/buckets/")
        hosts = sorted(b[len("aw-watcher-window_"):] for b in buckets if b.startswith("aw-watcher-window_"))
        host = self.settings.get("hostname")
        if host is None:
            if len(hosts) != 1:
                raise UserError("ActivityWatch needs one computer selected. Set activitywatch.hostname. Available hosts: " + (", ".join(hosts) or "none; enable the window watcher"))
            host = hosts[0]
        window, afk = f"aw-watcher-window_{host}", f"aw-watcher-afk_{host}"
        if window not in buckets:
            raise UserError(f"No window bucket for '{host}'. Enable the window watcher or correct hostname. Available: {', '.join(hosts)}")
        if afk not in buckets:
            raise UserError(f"No AFK watcher for '{host}'. Enable aw-watcher-afk; active time cannot be guessed safely.")
        web = sorted(b for b, meta in buckets.items() if b.startswith("aw-watcher-web-") and meta.get("hostname") == host) if self.settings.get("use_web") else []
        if self.settings.get("use_web") and not web:
            raise UserError(f"No web watcher for '{host}'. Install the ActivityWatch browser extension, or set use_web = false.")
        self.buckets = window, afk, web
        return f"ActivityWatch is reachable; window and AFK buckets found for {host}."

    def _events(self, bucket, start, end):
        path = f"/buckets/{quote(bucket, safe='')}/events"
        # The predecessor also covers servers which filter on event start time.
        rows = self.http.request("GET", path + "?" + urlencode({"start": iso(start), "end": iso(end), "limit": -1}))
        previous = self.http.request("GET", path + "?" + urlencode({"end": iso(start), "limit": 1}))
        events = []
        try:
            for row in rows + previous:
                if not isinstance(row["data"], dict):
                    raise ValueError("Event data must be an object")
                a = timestamp(row["timestamp"])
                b = a + timedelta(seconds=float(row["duration"]))
                if a < end and b > start:
                    events.append(Event(max(a, start), min(b, end), row["data"]))
        except (KeyError, TypeError, ValueError, OverflowError):
            raise UserError("ActivityWatch returned invalid events. Check the watcher version.") from None
        return events

    def fetch(self, start, end):
        if self.buckets is None:
            self.check()
        window, afk, web = self.buckets
        return Activity(self._events(window, start, end), self._events(afk, start, end),
                        [e for bucket in web for e in self._events(bucket, start, end)])
