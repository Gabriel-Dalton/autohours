from datetime import timedelta, timezone

import pytest

from autohours.models import Activity, Block
from autohours.pipeline import apply_caps, build
from autohours.review import html_review, text_review


def gap_activity(event):
    return Activity([event(0, 30, title="Acme private <title>")],
                    [event(0, 10, status="not-afk"), event(10, 13, status="afk"), event(13, 30, status="not-afk")])


@pytest.mark.parametrize("limit,minutes", [(0, 27), (2, 27), (3, 30), (5, 30)])
def test_break_policy_compressed_span(limit, minutes, event, projects, settings, origin):
    projects[0].agreement = {"count_breaks_up_to_minutes": limit}
    result = build(gap_activity(event), projects, settings, origin, origin + timedelta(hours=1), timezone.utc)
    assert [b.minutes for b in result.blocks] == [minutes]
    assert result.blocks[0].end == origin + timedelta(minutes=minutes)
    assert result.reviews[0].end == origin + timedelta(minutes=30)
    assert sum(s.minutes for s in result.reviews[0].segments if s.kind == "counted-break") == (3 if limit >= 3 else 0)


def test_missing_afk_not_counted_as_break(event, projects, settings, origin):
    projects[0].agreement = {"count_breaks_up_to_minutes": 5}
    activity = gap_activity(event)
    activity.afk.pop(1)
    result = build(activity, projects, settings, origin, origin + timedelta(hours=1), timezone.utc)
    assert result.blocks[0].minutes == 27


@pytest.mark.parametrize("enabled,app,title,expected", [
    (False, "Zoom", "Acme call", 0), (True, "Zoom", "Acme call", 20),
    (True, "Browser", "Acme Google Meet", 20), (True, "Editor", "Acme code", 0),
])
def test_calls_when_away(enabled, app, title, expected, event, projects, settings, origin):
    projects[0].agreement = {"count_calls_when_away": enabled}
    result = build(Activity([event(0, 20, app=app, title=title)], [event(0, 20, status="afk")]),
                   projects, settings, origin, origin + timedelta(hours=1), timezone.utc)
    assert sum(b.minutes for b in result.blocks) == expected
    if expected:
        assert "calls counted while away: 20.0" in text_review(result, projects, timezone.utc)


@pytest.mark.parametrize("mode,minutes,expected", [("nearest", 12, 10), ("nearest", 12.5, 15), ("up", 12, 15), ("up", 10, 10)])
def test_agreement_rounding(mode, minutes, expected, event, projects, settings, origin):
    projects[0].agreement = {"round_to_minutes": 5, "rounding": mode}
    result = build(Activity([event(0, minutes, title="Acme")], [event(0, 30, status="not-afk")]),
                   projects, settings, origin, origin + timedelta(hours=1), timezone.utc)
    assert result.blocks[0].minutes == expected
    assert result.reviews[0].rounding == expected - minutes


def test_cap_holds_partial_entry_and_counts_logged(event, projects, settings, origin):
    projects[0].agreement = {"monthly_cap_hours": .5}
    activity = Activity([event(0, 20, title="Acme"), event(40, 60, title="Acme")], [event(0, 60, status="not-afk")])
    result = build(activity, projects, settings, origin, origin + timedelta(hours=1), timezone.utc)
    assert [b.minutes for b in result.blocks] == [20, 10]
    assert result.reviews[1].held == 10
    result = build(activity, projects, settings, origin, origin + timedelta(hours=1), timezone.utc, caps=False)
    logged = [Block(origin - timedelta(days=1), origin - timedelta(days=1) + timedelta(minutes=25), "Acme Corp", "", True)]
    apply_caps(result, projects, timezone.utc, logged)
    assert [b.minutes for b in result.blocks] == [5]
    assert sum(r.held for r in result.reviews) == 35


def test_cap_overlap_does_not_spend_twice(event, projects, settings, origin):
    projects[0].agreement = {"monthly_cap_hours": .5}
    activity = Activity([event(0, 20, title="Acme"), event(40, 60, title="Acme")], [event(0, 60, status="not-afk")])
    result = build(activity, projects, settings, origin, origin + timedelta(hours=1), timezone.utc, caps=False)
    old = result.blocks[0]
    apply_caps(result, projects, timezone.utc, [old], [(old.start, old.end)])
    assert [b.minutes for b in result.blocks] == [20, 10]


def test_review_text_and_html_privacy(event, projects, settings, origin):
    projects[0].agreement = {"billing": "hourly", "rate": 120, "currency": "CAD"}
    result = build(gap_activity(event), projects, settings, origin, origin + timedelta(hours=1), timezone.utc)
    text = text_review(result, projects, timezone.utc)
    assert "worked 27.0 min; billed 27.0 min" in text
    assert "away gaps excluded: 3.0" in text
    assert "120 CAD x 0.45 hours = 54.00 CAD" in text
    html = html_review(result, projects, timezone.utc)
    assert "private" not in html and "<table>" in html and 'scope="col"' in html
    assert "http:" not in html and "https:" not in html and "<script" not in html
    assert "color-scheme:light dark" in html
    assert "private &lt;title&gt;" in html_review(result, projects, timezone.utc, True)
    projects[0].agreement.pop("rate")
    assert "rate not set" in text_review(result, projects, timezone.utc)


def test_cap_resets_at_local_month_boundary(projects, settings):
    from zoneinfo import ZoneInfo
    from autohours.models import Event, timestamp
    zone = ZoneInfo("America/Vancouver")
    start, end = timestamp("2026-11-01T06:40:00Z"), timestamp("2026-11-01T07:20:00Z")
    projects[0].agreement = {"monthly_cap_hours": .25}
    result = build(Activity([Event(start, end, {"title": "Acme"})], [Event(start, end, {"status": "not-afk"})]),
                   projects, settings, start, end, zone)
    assert [b.minutes for b in result.blocks] == [15, 15]
    assert [r.held for r in result.reviews] == [5, 5]


def test_rounding_never_crosses_midnight_or_next_block(event, projects, settings, origin):
    projects[0].agreement = {"round_to_minutes": 60, "rounding": "up"}
    settings["min_block_minutes"] = 0
    result = build(Activity([event(0, 5, title="Acme"), event(7, 20, title="course")], [event(0, 20, status="not-afk")]),
                   projects, settings, origin, origin + timedelta(hours=1), timezone.utc)
    assert result.blocks[0].end <= result.blocks[1].start
    late = origin.replace(hour=23, minute=55)
    from autohours.models import Event
    result = build(Activity([Event(late, late + timedelta(minutes=10), {"title": "Acme"})],
                            [Event(late, late + timedelta(minutes=10), {"status": "not-afk"})]),
                   projects, settings, late, late + timedelta(minutes=10), timezone.utc)
    assert [b.minutes for b in result.blocks] == [5, 5]


def test_calls_need_afk_and_project_evidence(event, projects, settings, origin):
    projects[0].agreement = {"count_calls_when_away": True}
    for activity in [Activity([event(0, 20, title="Acme", app="Zoom")], []),
                     Activity([event(0, 20, title="Unknown", app="Zoom")], [event(0, 20, status="afk")])]:
        assert not build(activity, projects, settings, origin, origin + timedelta(hours=1), timezone.utc).blocks


def test_round_up_exact_duration_with_fractional_slices(event, projects, settings, origin):
    projects[0].agreement = {"round_to_minutes": 5, "rounding": "up"}
    settings["min_block_minutes"] = 0
    windows = [event(i / 3, (i + 1) / 3, title="Acme") for i in range(15)]
    result = build(Activity(windows, [event(0, 5, status="not-afk")]), projects, settings,
                   origin, origin + timedelta(hours=1), timezone.utc)
    assert result.blocks[0].minutes == 5


def test_zero_cap_holds_everything(event, projects, settings, origin):
    projects[0].agreement = {"monthly_cap_hours": 0}
    result = build(gap_activity(event), projects, settings, origin, origin + timedelta(hours=1), timezone.utc)
    assert result.blocks == []
    assert result.reviews[0].held == 27
