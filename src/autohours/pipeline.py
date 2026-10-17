from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import math
import re

from .models import Activity, Block, Project


def classify(projects: list[Project], title="", app="", url=""):
    values = {"title": title, "app": app, "url": url}
    for index, project in enumerate(projects):
        if any(regex.search(values[field]) for field, rules in project.rules.items() for regex in rules):
            return index
    return None


@dataclass
class Slice:
    start: datetime
    end: datetime
    project: int | None
    app: str
    title: str


@dataclass
class Result:
    blocks: list[Block]
    unmatched: Counter
    discarded_minutes: float


def active_slices(activity: Activity, projects, start, end):
    """Sweep event boundaries, intersect AFK, and resolve duplicate watcher events."""
    boundaries = defaultdict(list)
    groups = (activity.windows, activity.afk, activity.web)
    for group, events in enumerate(groups):
        for index, event in enumerate(events):
            a, b = max(start, event.start), min(end, event.end)
            if a < b:
                boundaries[a].append((group, index, True))
                boundaries[b].append((group, index, False))
    points = sorted(boundaries)
    live = [set(), set(), set()]
    slices = []
    for pos, a in enumerate(points[:-1]):
        for group, index, opening in boundaries[a]:
            if opening:
                live[group].add(index)
            else:
                live[group].discard(index)
        b = points[pos + 1]
        if not live[0] or not live[1]:
            continue
        # Newest event wins overlapping input. AFK conflicts fail closed.
        if any(activity.afk[i].data.get("status") != "not-afk" for i in live[1]):
            continue
        window = max((activity.windows[i] for i in live[0]), key=lambda e: (e.start, str(e.data)))
        app = str(window.data.get("app", ""))
        title = str(window.data.get("title", ""))
        # Match the foreground title too, so a background browser cannot classify an editor.
        browser_title = re.sub(r"\s+[-\u2013\u2014]\s+(?:Google Chrome|Mozilla Firefox|Microsoft Edge|Brave|Opera|Safari)$", "", title, flags=re.I)
        web = [activity.web[i] for i in live[2]
               if activity.web[i].data.get("title") == browser_title
               and activity.web[i].data.get("incognito", False) is not True]
        url = str(max(web, key=lambda e: (e.start, str(e.data))).data.get("url", "")) if web else ""
        slices.append(Slice(a, b, classify(projects, title, app, url), app, title))
    return slices


def minute_winners(slices):
    """Choose greatest active duration per UTC minute; ties follow config order."""
    minutes = defaultdict(list)
    for item in slices:
        a = item.start
        while a < item.end:
            floor = a.replace(second=0, microsecond=0)
            b = min(item.end, floor + timedelta(minutes=1))
            minutes[floor].append(Slice(a, b, item.project, item.app, item.title))
            a = b
    result = []
    discarded = 0
    for pieces in minutes.values():
        totals = defaultdict(float)
        for s in pieces:
            totals[s.project] += (s.end - s.start).total_seconds()
        winner = min(totals, key=lambda p: (-totals[p], p if p is not None else math.inf))
        for s in pieces:
            if s.project is not None and s.project != winner:
                discarded += (s.end - s.start).total_seconds()
                # Keep a barrier so another project cannot bridge discarded work.
                result.append(Slice(s.start, s.end, None, s.app, s.title))
            else:
                result.append(s)
    return sorted(result, key=lambda s: s.start), discarded / 60


def build(activity, projects, settings, start, end, zone):
    raw = active_slices(activity, projects, start, end)
    unmatched = Counter()
    for s in raw:
        if s.project is None:
            unmatched[(s.app, s.title)] += (s.end - s.start).total_seconds() / 60
    slices, discarded = minute_winners(raw)
    merged = []
    current = None
    for s in slices:
        if s.project is None:
            current = None
            continue
        # Split at local midnight, including DST transitions.
        a = s.start
        while a < s.end:
            day = a.astimezone(zone).date()
            midnight = datetime.combine(day + timedelta(days=1), time(), zone).astimezone(timezone.utc)
            b = min(s.end, midnight)
            if (current is not None and current[2] == s.project
                    and current[0].astimezone(zone).date() == day
                    and (a - current[1]).total_seconds() <= settings["merge_gap_minutes"] * 60):
                current[1] = b
            else:
                current = [a, b, s.project]
                merged.append(current)
            a = b
    blocks = []
    minimum = settings["min_block_minutes"]
    quantum = settings["round_to_minutes"] * 60
    for a, b, project in merged:
        original = (b - a).total_seconds() / 60
        if quantum:
            a = datetime.fromtimestamp(math.ceil(a.timestamp() / quantum) * quantum, timezone.utc)
            b = datetime.fromtimestamp(math.floor(b.timestamp() / quantum) * quantum, timezone.utc)
        duration = max(0, (b - a).total_seconds() / 60)
        if duration <= 0 or duration < minimum:
            discarded += original
            continue
        discarded += original - duration
        p = projects[project]
        blocks.append(Block(a, b, p.destination_project, p.description, p.billable))
    return Result(blocks, unmatched, discarded)
