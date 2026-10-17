from datetime import date, timedelta, timezone
from importlib.resources import files

import pytest

from autohours import accepted
from autohours.cli import main
from autohours.config import load_config
from autohours.destinations import Clockify, sync
from autohours.models import Activity, UserError, iso
from autohours.pipeline import build
from autohours.plugins import SOURCES
from autohours.rates import compare
from test_destinations import StubClockify


def config_file(tmp_path, extra=""):
    path = tmp_path / "autohours.toml"
    text = files("autohours").joinpath("starter.toml").read_text(encoding="utf-8")
    path.write_text(text.replace('timezone = "America/Vancouver"', 'timezone = "UTC"') + extra, encoding="utf-8")
    return load_config(path)


def test_accept_list_remove_and_sync_privacy(tmp_path, monkeypatch, capsys):
    config = config_file(tmp_path)
    args = ["--config", str(config.path)]
    assert main(args + ["accept", "2026-10-16", "14:00", "14:30", "--project", "Acme Corp", "--note", 'private "call"']) == 0
    rows = accepted.load(config)
    assert len(rows) == 1 and rows[0].note == 'private "call"'
    assert main(args + ["accepted", "2026-10-16"]) == 0
    assert rows[0].id in capsys.readouterr().out
    class Source:
        def fetch(self, start, end):
            return Activity([], [])
    monkeypatch.setitem(SOURCES, "activitywatch", lambda config: Source())
    html = tmp_path / "review.html"
    assert main(args + ["review", "2026-10-16", "--html", str(html)]) == 0
    assert "accepted: 30.0" in capsys.readouterr().out
    assert "private" not in html.read_text()
    assert main(args + ["sync", "2026-10-16", "--write"]) == 0
    output = (tmp_path / "timesheet.csv").read_text()
    assert "30.00" in output and "private" not in output
    assert main(args + ["accept", "--remove", rows[0].id]) == 0
    assert accepted.load(config) == []
    assert (tmp_path / "timesheet.csv").read_text() == output


def test_accepted_deduplicates_observed_and_skips_clockify(tmp_path, event, settings, origin):
    config = config_file(tmp_path)
    item = accepted.add(config, date(2026, 10, 16), "09:05", "09:15", "Acme Corp")
    result = build(Activity([event(0, 20, title="Acme")], [event(0, 20, status="not-afk")]),
                   config.projects, settings, origin, origin + timedelta(hours=1), timezone.utc, [item])
    assert sum(b.minutes for b in result.blocks) == 20
    assert sum(s.minutes for s in result.reviews[0].segments if s.kind == "accepted") == 10
    http = StubClockify([{"timeInterval": {"start": iso(origin), "end": iso(origin + timedelta(minutes=1))}}])
    # The stub only contains the projects used here.
    dest = Clockify({"workspace": "My workspace"}, config.projects[:1], http)
    assert sync(dest, result.blocks, origin, origin + timedelta(hours=1), True) == (0, 1)
    assert http.posts == []
    http = StubClockify()
    dest = Clockify({"workspace": "My workspace"}, config.projects[:1], http)
    assert sync(dest, result.blocks, origin, origin + timedelta(hours=1), True) == (1, 0)
    assert set(http.posts[0]) == {"start", "end", "description", "billable", "projectId"}


def test_accept_validation_and_private_file_preservation(tmp_path):
    config = config_file(tmp_path)
    item = accepted.add(config, date(2026, 10, 16), "09:00", "09:30", "Acme Corp")
    original = accepted.path_for(config).read_bytes()
    for start, end, project in [("09:10", "09:20", "Acme Corp"), ("10:00", "09:00", "Acme Corp"), ("10:00", "11:00", "Unknown")]:
        with pytest.raises(UserError):
            accepted.add(config, date(2026, 10, 16), start, end, project)
    with pytest.raises(UserError):
        accepted.remove(config, "missing")
    assert accepted.path_for(config).read_bytes() == original
    assert accepted.load(config)[0].id == item.id


def test_accept_dst_ambiguous_and_nonexistent():
    from zoneinfo import ZoneInfo
    zone = ZoneInfo("America/Vancouver")
    for day, clock in [(date(2025, 11, 2), "01:30"), (date(2025, 3, 9), "02:30")]:
        with pytest.raises(UserError, match="DST"):
            accepted.local_time(day, clock, zone)
    assert accepted.local_time(date(2025, 11, 2), "01:30-07:00", zone).hour == 8


class RateHTTP(StubClockify):
    def __init__(self, currency="CAD", mismatch=False):
        super().__init__()
        self.currency = currency
        self.mismatch = mismatch
        self.project = {"name": "Acme Corp", "public": True, "billable": False,
                        "color": "#123456", "hourlyRate": {"amount": 5000, "currency": currency}}
        self.puts = []
        self.reads = 0

    def request(self, method, path, body=None):
        if path == "/workspaces/workspace-fake":
            return {"hourlyRate": {"currency": self.currency}}
        if path == "/workspaces/workspace-fake/projects/project-acme":
            if method == "PUT":
                self.puts.append(body)
                if not self.mismatch:
                    self.project["billable"] = body["billable"]
                    if "hourlyRate" in body:
                        self.project["hourlyRate"] = {"amount": body["hourlyRate"]["amount"], "currency": self.currency}
            else:
                self.reads += 1
            return self.project.copy()
        return super().request(method, path, body)


def test_rates_diff_apply_readback(projects):
    projects[0].agreement = {"billing": "hourly", "rate": 125.50, "currency": "CAD"}
    http = RateHTTP()
    dest = Clockify({"workspace": "My workspace"}, projects[:1], http)
    messages, failed = compare(dest)
    assert not failed and not http.puts
    assert "50.00 CAD/h -> 125.50 CAD/h" in "\n".join(messages)
    messages, failed = compare(dest, True)
    assert not failed and "confirmed" in "\n".join(messages)
    assert http.reads == 3
    assert http.puts == [{"name": "Acme Corp", "color": "#123456", "isPublic": True, "billable": True,
                          "hourlyRate": {"amount": 12550, "includeApproved": False}, "hourlyRateSet": True}]


@pytest.mark.parametrize("currency,mismatch,expected", [("USD", False, "refusing"), ("CAD", True, "MISMATCH")])
def test_rates_refuse_currency_and_report_mismatch(projects, currency, mismatch, expected):
    projects[0].agreement = {"billing": "hourly", "rate": 100, "currency": "CAD"}
    http = RateHTTP(currency, mismatch)
    messages, failed = compare(Clockify({"workspace": "My workspace"}, projects[:1], http), True)
    assert failed and expected in "\n".join(messages)
    if currency == "USD":
        assert http.puts == []


def test_rates_no_rate_never_sets_one(projects):
    projects[0].agreement = {"billing": "hourly"}
    http = RateHTTP()
    messages, failed = compare(Clockify({"workspace": "My workspace"}, projects[:1], http), True)
    assert not failed and "rate not set" in "\n".join(messages)
    assert "hourlyRate" not in http.puts[0]


def test_rates_in_sync_money_and_no_unnecessary_put(projects):
    projects[0].agreement = {"billing": "hourly", "rate": 100, "currency": "USD"}
    http = RateHTTP("USD")
    http.project.update(billable=True, hourlyRate={"amount": 10000, "currency": "USD"})
    messages, failed = compare(Clockify({"workspace": "My workspace"}, projects[:1], http), True)
    assert not failed and not http.puts
    assert messages == ["Acme Corp: in sync (billable, 100.00 USD/h)"]


def test_policy_defaults_and_project_overrides(tmp_path):
    config = config_file(tmp_path)
    text = config.path.read_text()
    text = text.replace('count_breaks_up_to_minutes = 0', 'count_breaks_up_to_minutes = 5')
    text = text.replace('count_calls_when_away = false', 'count_calls_when_away = true')
    text = text.replace('rounding = "nearest"', 'rounding = "up"')
    text += '\n[projects.agreement]\nbilling = "none"\ncount_breaks_up_to_minutes = 0\ncount_calls_when_away = false\nround_to_minutes = 15\n'
    config.path.write_text(text)
    cfg = load_config(config.path)
    assert cfg.projects[0].agreement["count_breaks_up_to_minutes"] == 5
    assert cfg.projects[0].agreement["count_calls_when_away"] is True
    assert cfg.projects[-1].agreement["count_breaks_up_to_minutes"] == 0
    assert cfg.projects[-1].agreement["count_calls_when_away"] is False
    assert cfg.projects[-1].agreement["round_to_minutes"] == 15
    assert not cfg.projects[-1].billable


@pytest.mark.parametrize("setting", ['rate = -1', 'rate = nan', 'rate = true', 'currency = "usd"',
                                    'billing = "guess"', 'rounding = "down"', 'monthly_cap_hours = inf',
                                    'count_calls_when_away = 1', 'call_apps = ["["]', 'round_to_minutes = 1.5'])
def test_agreement_validation(tmp_path, setting):
    with pytest.raises(UserError):
        config_file(tmp_path, '\n[projects.agreement]\n' + setting + '\n')


def test_cli_month_cap_uses_earlier_local_activity_and_logged_time(tmp_path, monkeypatch, event, origin, capsys):
    from autohours.destinations import CSV
    from autohours.models import Block, Event
    config = config_file(tmp_path)
    text = config.path.read_text().replace('billing = "hourly"', 'billing = "hourly"\nmonthly_cap_hours = 0.5')
    config.path.write_text(text)
    config = load_config(config.path)
    previous = origin - timedelta(days=1)
    class Source:
        def fetch(self, start, end):
            return Activity([Event(previous, previous + timedelta(minutes=20), {"title": "Acme"}), event(0, 20, title="Acme")],
                            [Event(previous, previous + timedelta(minutes=20), {"status": "not-afk"}), event(0, 20, status="not-afk")])
    monkeypatch.setitem(SOURCES, "activitywatch", lambda config: Source())
    args = ["--config", str(config.path)]
    assert main(args + ["review", "2026-10-16"]) == 0
    output = capsys.readouterr().out
    assert "held back by cap: 10.0" in output
    assert "billed 10.0" in output
    assert main(args + ["preview", "2026-10-16"]) == 0
    assert "held back by cap: 10.0" in capsys.readouterr().out
    dest = CSV(config.destination, timezone.utc)
    dest.create(Block(previous, previous + timedelta(minutes=25), "Acme Corp", "Manual", True))
    assert main(args + ["sync", "2026-10-16"]) == 0
    assert "held back by cap: 15.0" in capsys.readouterr().out
    assert main(args + ["sync", "2026-10-16", "--write"]) == 0
    assert main(args + ["sync", "2026-10-16", "--write"]) == 0
    assert "Created 0, skipped 1" in capsys.readouterr().out
    logged = dest.logged(previous, origin + timedelta(days=1))
    assert sum(b.minutes for b in logged) == 30


def test_clockify_logged_month_clipping_running_and_pagination(origin, projects):
    rows = [{"id": str(i), "projectId": "project-acme", "timeInterval": {
        "start": iso(origin - timedelta(days=2)), "end": iso(origin - timedelta(days=1))}} for i in range(100)]
    rows += [{"id": "cross", "projectId": "project-acme", "timeInterval": {
        "start": iso(origin - timedelta(minutes=5)), "end": iso(origin + timedelta(minutes=10))}},
        {"id": "running", "projectId": "project-learning", "timeInterval": {
            "start": iso(origin + timedelta(minutes=50)), "end": None}}]
    http = StubClockify(rows)
    dest = Clockify({"workspace": "My workspace"}, projects, http)
    logged = dest.logged(origin, origin + timedelta(hours=1))
    assert [(b.project, b.minutes) for b in logged] == [("Acme Corp", 10), ("Learning", 10)]


def test_rates_cli_dry_apply_and_non_clockify(tmp_path, monkeypatch, capsys):
    from autohours.plugins import DESTINATIONS
    config = config_file(tmp_path)
    args = ["--config", str(config.path)]
    assert main(args + ["rates"]) == 1
    text = config.path.read_text().replace('type = "csv"', 'type = "clockify"\nworkspace = "My workspace"')
    config.path.write_text(text)
    http = RateHTTP()
    monkeypatch.setitem(DESTINATIONS, "clockify", lambda cfg: Clockify(cfg.destination, cfg.projects[:1], http))
    assert main(args + ["rates"]) == 0
    assert not http.puts
    assert main(args + ["rates", "--apply"]) == 0
    assert "rate not set" in capsys.readouterr().out
    assert http.puts[0]["billable"] is True
