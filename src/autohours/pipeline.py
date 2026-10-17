from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, time, timedelta, timezone
import re

from .models import Activity, Block, Project
from .config import POLICY


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
    kind: str = "worked"

    @property
    def minutes(self):
        return (self.end - self.start).total_seconds() / 60


@dataclass
class ReviewBlock:
    start: datetime
    end: datetime
    project: int
    segments: list[Slice]
    billed: float
    rounding: float = 0
    held: float = 0
    filtered: bool = False
    entry_start: datetime | None = None


def agreement(project):
    return {**POLICY, **(project.agreement or {})}


@dataclass
class Result:
    blocks: list[Block]
    unmatched: Counter
    discarded_minutes: float
    reviews: list[ReviewBlock] = field(default_factory=list)
    segments: list[Slice] = field(default_factory=list)


def active_slices(activity: Activity, projects, start, end, include_away=False):
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
        if not live[0]:
            continue
        # Newest event wins overlapping input. AFK conflicts fail closed.
        active = bool(live[1]) and all(activity.afk[i].data.get("status") == "not-afk" for i in live[1])
        window = max((activity.windows[i] for i in live[0]), key=lambda e: (e.start, str(e.data)))
        app = str(window.data.get("app", ""))
        title = str(window.data.get("title", ""))
        # Match the foreground title too, so a background browser cannot classify an editor.
        browser_title = re.sub(r"\s+[-\u2013\u2014]\s+(?:Google Chrome|Mozilla Firefox|Microsoft Edge|Brave|Opera|Safari)$", "", title, flags=re.I)
        web = [activity.web[i] for i in live[2]
               if activity.web[i].data.get("title") == browser_title
               and activity.web[i].data.get("incognito", False) is not True]
        url = str(max(web, key=lambda e: (e.start, str(e.data))).data.get("url", "")) if web else ""
        project = classify(projects, title, app, url)
        kind = "worked" if active else "excluded-away"
        if not active and project is not None and any(activity.afk[i].data.get("status") == "afk" for i in live[1]):
            policy = agreement(projects[project])
            if policy["count_calls_when_away"] and (
                    any(re.search(p, app, re.I) for p in policy["call_apps"])
                    or any(re.search(p, title, re.I) for p in policy["call_titles"])):
                kind = "call"
        if include_away or kind != "excluded-away":
            slices.append(Slice(a, b, project, app, title, kind))
    return slices


def build(activity, projects, settings, start, end, zone, accepted=(), caps=True):
    raw = active_slices(activity, projects, start, end, include_away=True)
    # Explicit acceptance replaces evidence, never adds duplicate time.
    for item in accepted:
        a, b = max(start, item.start), min(end, item.end)
        if a >= b:
            continue
        remaining = []
        for s in raw:
            if s.end <= a or s.start >= b:
                remaining.append(s)
            else:
                if s.start < a:
                    remaining.append(replace(s, end=a))
                if s.end > b:
                    remaining.append(replace(s, start=b))
        remaining.append(Slice(a, b, item.project, "", "", "accepted"))
        raw = remaining
    raw.sort(key=lambda s: s.start)
    unmatched = Counter()
    for s in raw:
        if s.project is None and s.kind != "excluded-away":
            unmatched[(s.app, s.title)] += s.minutes
    eligible = [s for s in raw if s.kind != "excluded-away"]
    # The boundary sweep already resolves overlapping evidence. Preserve exact
    # seconds even when multiple projects share a calendar minute.
    discarded = 0
    merged = []
    pending = {}
    for position, s in enumerate(eligible):
        if s.project is None:
            continue
        current = pending.get(s.project)
        a = s.start
        while a < s.end:
            day = a.astimezone(zone).date()
            midnight = datetime.combine(day + timedelta(days=1), time(), zone).astimezone(timezone.utc)
            b = min(s.end, midnight)
            if (current is not None and current.project == s.project
                    and current.start.astimezone(zone).date() == day
                    and (a - current.end).total_seconds() <= settings["merge_gap_minutes"] * 60):
                if current.end < a:
                    gap = (a - current.end).total_seconds() / 60
                    away = sorted((max(current.end, x.start), min(a, x.end)) for x in activity.afk
                                  if x.data.get("status") == "afk" and x.start < a and x.end > current.end)
                    covered, cursor = 0, current.end
                    for left, right in away:
                        covered += max(0, (right - max(cursor, left)).total_seconds() / 60)
                        cursor = max(cursor, right)
                    # Another project's calls/accepted work can overlap AFK
                    # evidence. Never count that time again as a break.
                    interrupted = position > 0 and eligible[position - 1].end > current.end
                    is_away = covered >= gap - 1e-9 and not interrupted
                    counted = is_away and gap <= agreement(projects[s.project])["count_breaks_up_to_minutes"]
                    kind = "counted-break" if counted else "excluded-away" if is_away else "interruption"
                    current.segments.append(Slice(current.end, a, s.project, "", "", kind))
                current.end = b
                current.segments.append(replace(s, start=a, end=b))
            else:
                current = ReviewBlock(a, b, s.project, [replace(s, start=a, end=b)], 0)
                merged.append(current)
                pending[s.project] = current
            a = b
    candidates = []
    for row in merged:
        p = projects[row.project]
        policy = agreement(p)
        worked = sum((s.end - s.start for s in row.segments
                      if s.kind in ("worked", "call", "accepted", "counted-break")), timedelta())
        original = worked.total_seconds() / 60
        quantum = policy.get("round_to_minutes", settings["round_to_minutes"])
        duration = original
        if quantum:
            micros = (worked.days * 86400 + worked.seconds) * 1000000 + worked.microseconds
            step = quantum * 60 * 1000000
            units = (micros + step - 1) // step if policy["rounding"] == "up" else (2 * micros + step) // (2 * step)
            duration = units * quantum
        row.rounding = duration - original
        if duration <= 0 or (duration < settings["min_block_minutes"] and not any(s.kind == "accepted" for s in row.segments)):
            row.filtered = True
            discarded += original
            continue
        candidates.append((row, original, duration))

    # Interleaved projects have overlapping evidence spans. Pack each connected
    # group in first-seen order, retaining the real spans on the review rows.
    groups = []
    for candidate in candidates:
        row = candidate[0]
        if (groups and row.start < group_end
                and row.start.astimezone(zone).date() == groups[-1][0][0].start.astimezone(zone).date()):
            groups[-1].append(candidate)
            group_end = max(group_end, row.end)
        else:
            groups.append([candidate])
            group_end = row.end
    blocks = []
    for index, group in enumerate(groups):
        first = group[0][0].start
        midnight = datetime.combine(first.astimezone(zone).date() + timedelta(days=1), time(), zone).astimezone(timezone.utc)
        limit = min(end, midnight, groups[index + 1][0][0].start if index + 1 < len(groups) else end)
        # Reserve unrounded (or rounded-down) work before allowing rounding up.
        reserved = sum(min(original, duration) for _, original, duration in group)
        cursor = first
        for row, original, desired in group:
            reserved -= min(original, desired)
            entry_start = max(row.start, cursor)
            duration = min(desired, max(0, (limit - entry_start).total_seconds() / 60 - reserved))
            row.rounding = duration - original
            if duration <= 0 or (duration < settings["min_block_minutes"] and not any(s.kind == "accepted" for s in row.segments)):
                row.filtered = True
                discarded += original
                continue
            discarded += max(0, original - duration)
            row.billed = duration
            row.entry_start = entry_start
            p = projects[row.project]
            cursor = entry_start + timedelta(minutes=duration)
            blocks.append(Block(entry_start, cursor, p.destination_project, p.description, p.billable))
    result = Result(blocks, unmatched, discarded, merged, raw)
    if caps:
        apply_caps(result, projects, zone)
    return result


def month_key(moment, zone):
    local = moment.astimezone(zone)
    return local.year, local.month


def apply_caps(result, projects, zone, logged=(), existing=()):
    """Reserve logged time first; skipped overlaps do not spend the cap twice."""
    from .models import overlaps

    used = defaultdict(float)
    for block in logged:
        a = block.start
        while a < block.end:
            local = a.astimezone(zone)
            next_month = (local.replace(day=28) + timedelta(days=4)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            b = min(block.end, next_month.astimezone(timezone.utc))
            used[(block.project, month_key(a, zone))] += (b - a).total_seconds() / 60
            a = b
    output = []
    rows = {r.entry_start: r for r in result.reviews if r.billed > 0}
    for block in result.blocks:
        row = rows[block.start]
        cap = agreement(projects[row.project]).get("monthly_cap_hours")
        if cap is None or any(overlaps((block.start, block.end), old) for old in existing):
            output.append(block)
            continue
        key = block.project, month_key(block.start, zone)
        allowed = min(block.minutes, max(0, cap * 60 - used[key]))
        row.held = block.minutes - allowed
        row.billed = allowed
        if allowed > 0:
            output.append(replace(block, end=block.start + timedelta(minutes=allowed)))
            used[key] += allowed
    result.blocks = output
