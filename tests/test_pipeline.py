from datetime import timedelta, timezone
from zoneinfo import ZoneInfo
import re

from autohours.models import Activity, Project
from autohours.pipeline import active_slices, build, classify


def run(event, projects, settings, origin, windows, afk=None, web=None):
    return build(Activity(windows, afk if afk is not None else [event(0, 120, status="not-afk")], web or []),
                 projects, settings, origin, origin + timedelta(hours=2), timezone.utc)


def test_afk_intersection_and_missing_coverage(event, projects, origin):
    activity = Activity([event(0, 30, title="Acme")], [event(5, 15, status="not-afk"), event(15, 20, status="afk"), event(25, 40, status="not-afk")])
    slices = active_slices(activity, projects, origin, origin + timedelta(minutes=30))
    assert [(s.start, s.end) for s in slices] == [(origin + timedelta(minutes=5), origin + timedelta(minutes=15)), (origin + timedelta(minutes=25), origin + timedelta(minutes=30))]
    assert active_slices(Activity(activity.windows, []), projects, origin, origin + timedelta(hours=1)) == []


def test_order_any_rule_case_insensitive(projects):
    assert classify(projects, "ACME course") == 0
    assert classify(projects, "other", "studyapp") == 1
    assert classify(list(reversed(projects)), "Acme course") == 0
    assert classify(projects, "other") is None


def test_merge_and_minimum(event, projects, settings, origin):
    result = run(event, projects, settings, origin, [event(0, 6, title="Acme"), event(10, 20, title="Acme"), event(30, 35, title="Acme")])
    assert [b.minutes for b in result.blocks] == [20]
    assert result.discarded_minutes == 5


def test_unmatched_and_other_projects_are_barriers(event, projects, settings, origin):
    settings["min_block_minutes"] = 0
    result = run(event, projects, settings, origin, [event(0, 10, title="Acme"), event(10, 11, title="personal"), event(11, 21, title="Acme"), event(21, 22, title="course"), event(22, 32, title="Acme")])
    assert [b.minutes for b in result.blocks] == [10, 10, 1, 10]
    assert sum(result.unmatched.values()) == 1


def test_rounding_is_inward_and_cannot_overlap(event, projects, settings, origin):
    settings.update(min_block_minutes=0, round_to_minutes=5)
    result = run(event, projects, settings, origin, [event(1, 19, title="Acme"), event(19, 36, title="course")])
    assert [(b.start.minute, b.end.minute) for b in result.blocks] == [(5, 15), (20, 35)]
    assert result.discarded_minutes == 10
    settings["min_block_minutes"] = 20
    assert run(event, projects, settings, origin, [event(1, 22, title="Acme")]).blocks == []


def test_minute_conflict_no_reassignment(event, projects, settings, origin):
    settings.update(min_block_minutes=0, merge_gap_minutes=0)
    result = run(event, projects, settings, origin, [event(0, 0.4, title="Acme"), event(0.4, 1, title="course")])
    assert len(result.blocks) == 1
    assert result.blocks[0].project == "Learning"
    assert result.blocks[0].minutes == 0.6
    assert result.discarded_minutes == 0.4


def test_unmatched_minute_wins_without_export(event, projects, settings, origin):
    settings["min_block_minutes"] = 0
    result = run(event, projects, settings, origin, [event(0, 0.4, title="Acme"), event(0.4, 1, title="personal")])
    assert not result.blocks
    assert sum(result.unmatched.values()) == 0.6


def test_duplicate_events_count_once_and_afk_conflict_fails_closed(event, projects, settings, origin):
    result = run(event, projects, settings, origin, [event(0, 20, title="Acme")] * 2, [event(0, 20, status="not-afk")] * 2)
    assert [b.minutes for b in result.blocks] == [20]
    result = run(event, projects, settings, origin, [event(0, 20, title="Acme")], [event(0, 20, status="not-afk"), event(0, 20, status="afk")])
    assert not result.blocks


def test_web_only_matches_foreground_title(event, settings, origin):
    projects = [Project("Web", "Web", "Work", False, {"url": [re.compile(r"acme\.example")]})]
    good = event(0, 20, title="Acme page", url="https://acme.example/")
    result = run(event, projects, settings, origin, [event(0, 20, title="Acme page", app="Browser")], web=[good])
    assert len(result.blocks) == 1
    assert not run(event, projects, settings, origin, [event(0, 20, title="Editor", app="Editor")], web=[good]).blocks
    assert len(run(event, projects, settings, origin, [event(0, 20, title="Acme page - Google Chrome", app="chrome.exe")], web=[good]).blocks) == 1


def test_local_midnight_split(event, projects, settings, origin):
    zone = ZoneInfo("America/Vancouver")
    start = origin.replace(hour=6, minute=50)
    end = start + timedelta(minutes=30)
    from autohours.models import Event
    result = build(Activity([Event(start, end, {"title": "Acme"})], [Event(start, end, {"status": "not-afk"})]), projects, settings, start, end, zone)
    assert [b.minutes for b in result.blocks] == [10, 20]
    assert [b.start.astimezone(zone).day for b in result.blocks] == [15, 16]


def test_dst_repeated_hour_keeps_elapsed_time(projects, settings):
    from autohours.models import Event, timestamp
    zone = ZoneInfo("America/Vancouver")
    start, end = timestamp("2025-11-02T08:30:00Z"), timestamp("2025-11-02T10:30:00Z")
    result = build(Activity([Event(start, end, {"title": "Acme"})], [Event(start, end, {"status": "not-afk"})]), projects, settings, start, end, zone)
    assert [b.minutes for b in result.blocks] == [120]
