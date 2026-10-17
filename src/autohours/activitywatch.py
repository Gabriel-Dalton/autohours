from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, time, timedelta, timezone
import threading
from time import monotonic
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


class SessionActivityWatch(ActivityWatch):
    """Bounded, private preview cache. Writes always use a fresh source.

    Completed local days expire after five minutes to allow imported/corrected
    history to appear. Today is never cached. Discovery expires after 30 seconds.
    """
    def __init__(self, settings, zone, http=None):
        super().__init__(settings, http)
        self.zone = zone
        self.lock = threading.RLock()
        self.checked_at = float("-inf")
        self.message = ""
        self.days = {}

    def check(self, buckets=None):
        with self.lock:
            if buckets is not None or monotonic() - self.checked_at >= 30:
                previous = self.buckets
                self.message = super().check(buckets)
                if previous != self.buckets:
                    self.days.clear()
                self.checked_at = monotonic()
            return self.message

    def fetch(self, start, end):
        with self.lock:
            self.check()
            window, afk, web = self.buckets
            today = datetime.now(self.zone).date()
            self.days = {key: value for key, value in self.days.items()
                         if monotonic() - value[0] < 300 and key[0].astimezone(self.zone).date() < today}
            ranges = []
            cursor = start
            while cursor < end:
                midnight = datetime.combine(cursor.astimezone(self.zone).date() + timedelta(days=1), time(), self.zone).astimezone(timezone.utc)
                stop = min(end, midnight)
                ranges.append((cursor, stop))
                cursor = stop
            # Fetch adjacent missing days as one interval, including monthly cap
            # history. Do not turn a month preview into thirty HTTP round trips.
            groups = []
            for key in ranges:
                if key in self.days:
                    continue
                if groups and groups[-1][-1][1] == key[0]:
                    groups[-1].append(key)
                else:
                    groups.append([key])
            fetched = {}
            with ThreadPoolExecutor(max_workers=4) as pool:
                for group in groups:
                    jobs = [pool.submit(self._events, bucket, group[0][0], group[-1][1]) for bucket in (window, afk, *web)]
                    rows = [job.result() for job in jobs]
                    columns = (rows[0], rows[1], [event for events in rows[2:] for event in events])
                    for left, right in group:
                        activity = Activity(*[[replace(event, start=max(event.start, left), end=min(event.end, right))
                                              for event in column if event.start < right and event.end > left]
                                             for column in columns])
                        fetched[(left, right)] = activity
                        if right <= datetime.combine(today, time(), self.zone).astimezone(timezone.utc):
                            self.days[(left, right)] = (monotonic(), activity)
            result = Activity([], [], [])
            for key in ranges:
                activity = fetched[key] if key in fetched else self.days[key][1]
                result.windows.extend(activity.windows)
                result.afk.extend(activity.afk)
                result.web.extend(activity.web)
            while len(self.days) > 62:
                self.days.pop(next(iter(self.days)))
            return deepcopy(result)
