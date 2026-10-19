from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from autohours.cli import date_range, main, parser
from autohours.config import load_config
from autohours.models import UserError


def config_file(tmp_path, text=None):
    path = tmp_path / "autohours.toml"
    path.write_text(text or files("autohours").joinpath("starter.toml").read_text(), encoding="utf-8")
    return path


@pytest.mark.parametrize("day,hours", [("2025-03-09", 23), ("2025-11-02", 25), ("2026-10-16", 24)])
def test_dst_day_boundaries(day, hours):
    a, b = date_range([day], ZoneInfo("America/Vancouver"))
    assert (b - a).total_seconds() == hours * 3600


def test_relative_dates_local_today_and_inclusive_range():
    zone = ZoneInfo("America/Vancouver")
    now = datetime(2026, 10, 17, 1, tzinfo=timezone.utc)
    a, b = date_range([], zone, now)
    assert a.isoformat() == "2026-10-16T07:00:00+00:00"
    assert date_range(["today"], zone, now) == (a, b)
    assert date_range(["yesterday"], zone, now)[0].day == 15
    a, b = date_range(["2026-10-14", "2026-10-16"], zone)
    assert (b - a).days == 3


@pytest.mark.parametrize("values", [["wrong"], ["2026-02-30"], ["20261016"], ["2026-10-17", "2026-10-16"], ["today"] * 3])
def test_bad_dates(values):
    with pytest.raises(UserError):
        date_range(values, ZoneInfo("UTC"))


@pytest.mark.parametrize("old,new,match", [
    ('timezone = "America/Vancouver"', 'timezone = "Invalid/Zone"', "Timezone"),
    ('min_block_minutes = 10', 'min_block_minutes = -1', "whole number"),
    ('round_to_minutes = 0', 'round_to_minutes = true', "whole number"),
    ('use_web = false', 'use_web = "yes"', "true or false"),
    ('type = "csv"', 'type = "other"', "destination.type"),
    ('path = "timesheet.csv"', 'api_key = "fake-key"', "Unknown setting"),
    ("title = ['side-project']", "title = ['[']", "invalid title regex"),
    ("title = ['side-project']", 'title = "wrong"', "list"),
    ('url = "http://localhost:5600"', 'url = "https://remote.example"', "local HTTP"),
    ('billable = true', 'billable = "true"', "true/false"),
])
def test_config_validation(tmp_path, old, new, match):
    text = files("autohours").joinpath("starter.toml").read_text().replace(old, new)
    with pytest.raises(UserError, match=match):
        load_config(config_file(tmp_path, text))


def test_config_defaults_and_csv_relative_path(tmp_path):
    cfg = load_config(config_file(tmp_path))
    assert cfg.destination["path"] == str(tmp_path / "timesheet.csv")
    assert cfg.projects[1].destination_project == "Side project"


@pytest.mark.parametrize("text", [
    'timezone="UTC"\nactivitywatch="wrong"',
    'timezone="UTC"\nblocks=[]',
    'timezone="UTC"\ndestination="wrong"',
    'timezone="UTC"\n[destination]\ntype=[]',
    'timezone="UTC"\n[destination]\ntype="csv"\npath="times.csv"\nprojects=[]',
    'timezone="UTC"\n[bad',
])
def test_malformed_tables_have_friendly_errors(tmp_path, text):
    with pytest.raises(UserError):
        load_config(config_file(tmp_path, text))


def test_init_refuses_overwrite_and_rules_offline(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    original = Path("autohours.toml").read_bytes()
    assert main(["init"]) == 1
    assert Path("autohours.toml").read_bytes() == original
    assert main(["rules", "test", "ACME planning"]) == 0
    assert "Matches: Acme Corp" in capsys.readouterr().out


def test_expected_errors_are_friendly(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["preview"]) == 1
    assert main(["unknown-command"]) == 1
    output = capsys.readouterr().err
    assert "Traceback" not in output
    assert "init" in output


def test_starter_and_example_identical():
    assert files("autohours").joinpath("starter.toml").read_bytes() == Path("examples/autohours.example.toml").read_bytes()


def test_cli_preview_dry_run_write_and_repeat(tmp_path, monkeypatch, capsys, event):
    from autohours.models import Activity
    from autohours.plugins import SOURCES

    class FakeSource:
        def check(self):
            return "Watchers ready"
        def fetch(self, start, end):
            return Activity([event(0, 20, title="Acme private title")], [event(0, 20, status="not-afk")])

    monkeypatch.setitem(SOURCES, "activitywatch", lambda config: FakeSource())
    path = config_file(tmp_path)
    args = ["--config", str(path)]
    assert main(args + ["doctor"]) == 0
    assert main(args + ["preview", "2026-10-16"]) == 0
    assert main(args + ["sync", "2026-10-16"]) == 0
    assert not (tmp_path / "timesheet.csv").exists()
    assert "Would create 1" in capsys.readouterr().out
    assert main(args + ["sync", "2026-10-16", "--write"]) == 0
    assert main(args + ["sync", "2026-10-16", "--write"]) == 0
    assert "Created 0, skipped 1" in capsys.readouterr().out
    assert "private title" not in (tmp_path / "timesheet.csv").read_text()


@pytest.mark.parametrize("options", [[], ["--verbose"], ["--titles"], ["--verbose", "--titles"]])
def test_preview_and_review_share_output(tmp_path, monkeypatch, capsys, switching_activity, options):
    from autohours.plugins import SOURCES

    activity = switching_activity()
    class Source:
        def fetch(self, start, end):
            return activity
    monkeypatch.setitem(SOURCES, "activitywatch", lambda config: Source())
    path = config_file(tmp_path)
    path.write_text(path.read_text().replace("side-project", "course"), encoding="utf-8")
    args = ["--config", str(path)]
    assert main(args + ["preview", "2026-10-16"] + options) == 0
    preview = capsys.readouterr().out
    assert main(args + ["review", "2026-10-16"] + options) == 0
    assert capsys.readouterr().out == preview
    assert "Total billed:" in preview


def test_cli_legacy_console_encoding_for_stdout_and_stderr(tmp_path, monkeypatch, event):
    import io
    import sys
    from autohours.models import Activity
    from autohours.plugins import SOURCES

    title = "private \u2733 title"
    class Source:
        def fetch(self, start, end):
            return Activity([event(0, 20, title=title, app="Terminal")], [event(0, 20, status="not-afk")])
    monkeypatch.setitem(SOURCES, "activitywatch", lambda config: Source())
    args = ["--config", str(config_file(tmp_path))]
    output, errors = io.BytesIO(), io.BytesIO()
    stdout = io.TextIOWrapper(output, encoding="cp1252", errors="strict")
    stderr = io.TextIOWrapper(errors, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)
    assert main(args + ["unmatched", "2026-10-16"]) == 0
    assert main(["bad-command-\u2733"]) == 1
    stdout.flush()
    stderr.flush()
    assert "private ? title" in output.getvalue().decode("cp1252")
    assert "bad-command-?" in errors.getvalue().decode("cp1252")
    assert stdout.errors == stderr.errors == "replace"


def test_version_matches_package_metadata(capsys):
    import tomllib
    from pathlib import Path
    from autohours import __version__
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert __version__ == project["project"]["version"]
    with pytest.raises(SystemExit):
        parser().parse_args(["--version"])
    assert capsys.readouterr().out.strip() == f"autohours {__version__}"
