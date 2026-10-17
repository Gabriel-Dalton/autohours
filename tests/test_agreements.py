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


def test_review_dates_are_headings_and_times_are_local(event, projects, settings, origin):
    from zoneinfo import ZoneInfo
    zone = ZoneInfo("America/Vancouver")
    result = build(gap_activity(event), projects, settings, origin, origin + timedelta(hours=1), zone)
    text = text_review(result, projects, zone)
    html = html_review(result, projects, zone)
    assert "2026-10-16\n02:00 to 02:30" in text
    assert "Entry: 02:00 to 02:27" in text
    assert "<h3>2026-10-16</h3>" in html and "02:00 to 02:30" in html
    assert "2026-10-16T" not in text + html


def test_review_repeated_hour_retains_offset_and_midnight_retains_date():
    from zoneinfo import ZoneInfo
    from autohours.models import timestamp
    from autohours.review import span
    zone = ZoneInfo("America/Vancouver")
    assert span(timestamp("2025-11-02T08:30:00Z"), timestamp("2025-11-02T09:30:00Z"), zone) == "01:30 (-07:00) to 01:30 (-08:00)"
    assert span(timestamp("2026-10-16T06:30:00Z"), timestamp("2026-10-16T07:00:00Z"), zone) == "23:30 to 00:00 (2026-10-16)"


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


def test_another_projects_away_call_is_not_counted_as_break(event, projects, settings, origin):
    projects[0].agreement = {"count_breaks_up_to_minutes": 5}
    projects[1].agreement = {"count_calls_when_away": True}
    settings["min_block_minutes"] = 0
    activity = Activity([event(0, 10, title="Acme"), event(10, 13, title="course", app="Zoom"),
                         event(13, 23, title="Acme")],
                        [event(0, 10, status="not-afk"), event(10, 13, status="afk"),
                         event(13, 23, status="not-afk")])
    result = build(activity, projects, settings, origin, origin + timedelta(hours=1), timezone.utc)
    assert [b.minutes for b in result.blocks] == [20, 3]
    assert not any(s.kind == "counted-break" for r in result.reviews for s in r.segments)


def test_interleaved_caps_use_compressed_entry_start(event, projects, settings, origin):
    projects[1].agreement = {"monthly_cap_hours": .2}
    activity = Activity([event(0, 10, title="Acme"), event(10, 15, title="course"),
                         event(15, 20, title="Acme"), event(20, 30, title="course")],
                        [event(0, 30, status="not-afk")])
    result = build(activity, projects, settings, origin, origin + timedelta(minutes=30), timezone.utc)
    assert [b.minutes for b in result.blocks] == [15, 12]
    assert result.reviews[1].entry_start > result.reviews[1].start
    assert result.reviews[1].held == 3
    assert "held back by cap: 3.0" in text_review(result, projects, timezone.utc)


def test_interleaved_rounding_reserves_other_projects_work(event, projects, settings, origin):
    projects[0].agreement = {"round_to_minutes": 60, "rounding": "up"}
    activity = Activity([event(0, 10, title="Acme"), event(10, 15, title="course"),
                         event(15, 20, title="Acme"), event(20, 30, title="course")],
                        [event(0, 30, status="not-afk")])
    result = build(activity, projects, settings, origin, origin + timedelta(minutes=30), timezone.utc)
    assert [b.minutes for b in result.blocks] == [15, 15]
    assert result.blocks[0].end == result.blocks[1].start
    assert result.blocks[-1].end == origin + timedelta(minutes=30)


def test_busy_day_review_is_compact_and_verbose_preserves_evidence(switching_activity, projects, settings, origin):
    activity = switching_activity(hours=8)
    result = build(activity, projects, settings, origin, origin + timedelta(hours=8), timezone.utc)
    compact = text_review(result, projects, timezone.utc)
    verbose = text_review(result, projects, timezone.utc, verbose=True)
    assert len(compact.splitlines()) < 30
    assert len(verbose.splitlines()) > len(activity.windows)
    assert "Private chat" not in compact
    html = html_review(result, projects, timezone.utc)
    assert len(html.encode("utf-8")) < 150_000
    assert html.count('<th scope="row">') == len(result.blocks) + len(projects)
    assert "Private chat" not in html
    assert "Private chat" in html_review(result, projects, timezone.utc, titles=True)


def test_adjacent_html_segments_compact_across_private_titles(event, projects, settings, origin):
    activity = Activity([event(i / 60, (i + 1) / 60, title=f"Acme private {i}") for i in range(3600)],
                        [event(0, 60, status="not-afk")])
    result = build(activity, projects, settings, origin, origin + timedelta(hours=1), timezone.utc)
    html = html_review(result, projects, timezone.utc)
    assert html.count('class="segment worked"') == 1
    assert len(html.encode("utf-8")) < 8_000
    assert "private" not in html


def test_filtered_blocks_and_unmatched_slices_are_summarized(event, projects, settings, origin):
    windows = [event(i * 10, i * 10 + 1, title="Acme") for i in range(12)]
    windows += [event(i * 10 + 1, i * 10 + 3, title=f"private {i}", app=f"Chat {i}") for i in range(12)]
    result = build(Activity(windows, [event(0, 120, status="not-afk")]),
                   projects, settings, origin, origin + timedelta(hours=2), timezone.utc)
    text = text_review(result, projects, timezone.utc)
    assert "worked 1.0" not in text
    assert "Acme Corp: filtered out 12.0 min" in text
    assert text.count("min  Chat") == 10
    assert "short block filtered out" in text_review(result, projects, timezone.utc, verbose=True)
    html = html_review(result, projects, timezone.utc)
    assert "short block filtered out" not in html
    assert "Acme Corp: filtered out 12.0 min" in html
    assert "short block filtered out" in html_review(result, projects, timezone.utc, verbose=True)
