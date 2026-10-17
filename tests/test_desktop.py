from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from autohours import desktop, entry, runlog, schedule, setup
from autohours.config import load_config
from autohours.models import UserError
from autohours.pipeline import classify
from test_setup import services  # Shared synthetic, offline HTTP fixture.


def session(tmp_path):
    value = desktop.Session(tmp_path / "autohours.toml")
    value.raw.update(timezone="UTC", destination={"type": "csv", "path": str(tmp_path / "times.csv")})
    value.raw["projects"] = [{"name": "Example", "description": "Project work", "app": ["^Editor$"],
                              "agreement": {"billing": "none"}}]
    return value


def test_service_rules_coverage_and_no_remote_writes(tmp_path, services):
    value = session(tmp_path)
    value.now = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
    assert value.hosts() == ["fake"]
    value.raw["activitywatch"]["hostname"] = "fake"
    value.check_activity()
    value.assign(0, 0, True)
    assert value.coverage() == 100
    assert classify(value.config().projects, app="Acme.App+") == 0
    assert classify(value.config().projects, app="AcmeXApp") is None
    value.add_project("Second", "Second project work")
    value.assign(1, 0, True)
    assert setup.item_rule(*value.items[0][0]) not in value.raw["projects"][0].get("app", [])
    assert classify(value.config().projects, app="Acme.App+") == 1
    assert all(method == "GET" for _, method, _, _ in services.calls)


def test_quick_activity_check_only_requests_buckets(tmp_path, services):
    value = session(tmp_path)
    assert value.hosts() == ["fake"]
    value.raw["activitywatch"]["hostname"] = "fake"
    assert "AFK buckets found" in value.check_buckets()
    assert len(services.calls) == 1
    assert services.calls[0][1:3] == ("GET", "/buckets/")
    assert value.activity is None and value.items == []
    del value.activity_buckets["aw-watcher-afk_fake"]
    with pytest.raises(UserError, match="No AFK watcher"):
        value.check_buckets()
    assert len(services.calls) == 1


def test_deferred_activity_read_returns_data_without_mutating_session(tmp_path, services):
    value = session(tmp_path)
    value.now = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
    activity, items = value.read_activity(dict(value.raw["activitywatch"]))
    assert activity and items
    assert value.activity is None and value.items == []
    assert all(method == "GET" for _, method, _, _ in services.calls)


def test_service_key_create_save_and_duplicate_target(tmp_path, services, monkeypatch):
    value = session(tmp_path)
    value.raw["projects"] = []
    saved = []
    monkeypatch.setattr(setup, "save_key", lambda key, output: saved.append(key))
    assert value.check_key("synthetic-secret") == ["Example workspace"]
    value.choose_workspace(0)
    value.add_project("Example", "Project work", "p1")
    with pytest.raises(UserError, match="already assigned"):
        value.add_project("Another", "Work", "p1")
    value.add_project("Second", "Second work", create=True)
    for row in value.raw["projects"]:
        row.update(app=["^" + row["name"] + "$"], agreement={"billing": "none"})
    assert not saved and all(method == "GET" for _, method, _, _ in services.calls)
    value.save()
    assert saved == ["synthetic-secret"]
    assert value.key is None and value.pending == []
    assert "synthetic-secret" not in value.path.read_text()
    assert len([1 for _, method, _, _ in services.calls if method == "POST"]) == 1
    value.save()
    assert len([1 for _, method, _, _ in services.calls if method == "POST"]) == 1


def test_service_rejects_key_without_echo(tmp_path, services):
    value = session(tmp_path)
    with pytest.raises(UserError) as error:
        value.check_key("bad")
    assert "bad" not in str(error.value)
    assert value.key is None and value.http is None


def test_service_csv_save_review_and_dry_sync(tmp_path, services):
    value = session(tmp_path)
    value.raw["projects"][0]["app"] = ["^Acme\\.App\\+$"]
    value.save()
    cfg, result = value.review("2026-10-16")
    assert len(result.blocks) == 1
    assert result.blocks[0].minutes == 60
    assert "Would create 1" in value.command("sync", "2026-10-16")
    assert not (tmp_path / "times.csv").exists()
    assert "Created 1" in value.command("sync", "2026-10-16", "--write")
    assert "Created 0, skipped 1" in value.command("sync", "2026-10-16", "--write")
    assert "Acme launch" not in (tmp_path / "times.csv").read_text()
    report = desktop.full_report(cfg, result)
    try:
        assert report.parent != tmp_path and "Acme launch" not in report.read_text(encoding="utf-8")
        assert "<html" in report.read_text(encoding="utf-8")
    finally:
        report.unlink()


def test_service_blocks_changed_config_and_unsaved_writes(tmp_path, services):
    value = session(tmp_path)
    with pytest.raises(UserError, match="Settings changed"):
        value.command("sync", "yesterday", "--write")
    value.save()
    value.raw["projects"][0]["description"] = "Changed"
    with pytest.raises(UserError, match="Save your changed settings"):
        value.command("sync", "yesterday", "--write")
    value.path.write_text(value.path.read_text() + "\n# Changed elsewhere\n")
    with pytest.raises(UserError, match="changed during setup"):
        value.save()
    assert "Changed elsewhere" in value.path.read_text()


def test_edit_preserves_settings_comments_and_unedited_project(tmp_path):
    value = session(tmp_path)
    value.save()
    original = value.path.read_text().replace('timezone = "UTC"', '# Keep this comment\ntimezone = "UTC"')
    value.path.write_text(original)
    value = desktop.Session(value.path)
    value.add_project("Second", "Other work")
    value.raw["projects"][-1].update(app=["^Second$"], agreement={"billing": "none"})
    value.save()
    assert "# Keep this comment" in value.path.read_text()
    assert [p.name for p in load_config(value.path).projects] == ["Example", "Second"]


def test_edit_handles_top_level_tables_after_projects(tmp_path):
    value = session(tmp_path)
    text = setup.config_text(value.raw)
    before, after = text.split("[[projects]]", 1)
    zone, destination = before.split("[destination]", 1)
    value.path.write_text(zone + "[[projects]]" + after + "\n[destination]" + destination)
    value = desktop.Session(value.path)
    value.raw["projects"][0]["description"] = "Updated description"
    value.save()
    assert load_config(value.path).destination["path"] == str(tmp_path / "times.csv")


def test_desktop_rates_compare_apply_and_readback(tmp_path, services, monkeypatch):
    value = session(tmp_path)
    value.check_key("synthetic-secret")
    value.choose_workspace(0)
    value.raw["projects"][0].update(destination_project="p1", agreement={"billing": "hourly", "rate": 100, "currency": "CAD"})
    monkeypatch.setattr(setup, "save_key", lambda key, output: monkeypatch.setenv("CLOCKIFY_API_KEY", key))
    value.save()
    messages, failed = value.rates()
    assert not failed and any("50.00 CAD/h -> 100.00 CAD/h" in line for line in messages)
    assert not any(method == "PUT" for _, method, _, _ in services.calls)
    messages, failed = value.rates(True)
    assert not failed and any("confirmed" in line for line in messages)
    assert any(method == "PUT" for _, method, _, _ in services.calls)


def test_partial_project_creation_is_not_duplicated_on_retry(tmp_path, services, monkeypatch):
    value = session(tmp_path)
    value.raw["projects"] = []
    value.check_key("synthetic-secret")
    value.choose_workspace(0)
    value.add_project("Second", "Second work", create=True)
    value.raw["projects"][0].update(app=["Second"], agreement={"billing": "none"})
    monkeypatch.setattr(setup, "save_key", lambda *a: None)
    monkeypatch.setattr(setup, "atomic_write", lambda *a: (_ for _ in ()).throw(OSError("Disk full")))
    with pytest.raises(OSError):
        value.save()
    assert not value.path.exists()
    with pytest.raises(UserError, match="already has a project"):
        value.save()
    assert len([1 for _, method, _, _ in services.calls if method == "POST"]) == 1


def test_web_dates_are_explicit_and_do_not_shift_at_midnight():
    from autohours.webapp import valid_day
    assert valid_day("2026-10-16") == "2026-10-16"
    for value in ("yesterday", "today", "2026-02-30", "20261016"):
        with pytest.raises(UserError):
            valid_day(value)


def test_agreements_validate_optional_values_and_preserve_call_rules():
    fields = dict(billing="hourly", rate="", currency="", count_breaks_up_to_minutes="5",
                  count_calls_when_away=True, round_to_minutes="15", rounding="up", monthly_cap_hours="40")
    result = desktop.agreement(fields, {"call_apps": ["Example call"]})
    assert "rate" not in result and "currency" not in result
    assert result["count_breaks_up_to_minutes"] == 5 and result["monthly_cap_hours"] == 40
    assert result["call_apps"] == ["Example call"]
    for field, invalid in (("rate", "nan"), ("currency", "dollars"), ("round_to_minutes", "1.5"),
                           ("billing", ""), ("monthly_cap_hours", "-1")):
        with pytest.raises((UserError, ValueError)):
            desktop.agreement({**fields, field: invalid})


def test_log_tee_retention_and_no_console(tmp_path, monkeypatch, capsys):
    today = datetime(2026, 10, 17).date()
    for ago in range(33):
        (tmp_path / f"{today - timedelta(days=ago)}.log").write_text("Old")
    (tmp_path / "notes.log").write_text("Keep")
    with runlog.logging(tmp_path, today):
        print("Created 2, skipped 1 (already logged).")
        print("Run finished: success")
    assert "Created 2" in capsys.readouterr().out
    assert not (tmp_path / "2026-09-17.log").exists()
    assert (tmp_path / "2026-09-18.log").exists()
    assert (tmp_path / "notes.log").read_text() == "Keep"
    assert "Created 2" in runlog.last_result(tmp_path)
    monkeypatch.setattr(runlog.sys, "stdout", None)
    monkeypatch.setattr(runlog.sys, "stderr", None)
    with runlog.logging(tmp_path, today):
        print("Error: Offline")
    assert "Error: Offline" in runlog.last_result(tmp_path)


def test_entry_routes_no_args_cli_and_frozen_logs(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(entry.cli, "main", lambda args: calls.append(args) or 0)
    monkeypatch.setattr(runlog, "log_directory", lambda: tmp_path)
    assert entry.main([]) == 0 and calls[-1] == ["gui"]
    assert entry.main(["review", "yesterday"]) == 0 and calls[-1] == ["review", "yesterday"]
    assert not list(tmp_path.glob("*.log"))
    monkeypatch.setattr(entry.sys, "frozen", True, raising=False)
    assert entry.main(["sync", "yesterday", "--write"]) == 0
    assert "Run finished: success" in next(tmp_path.glob("*.log")).read_text()


def test_failed_unattended_command_is_logged_without_traceback(tmp_path, monkeypatch):
    monkeypatch.setattr(runlog, "log_directory", lambda: tmp_path / "logs")
    config = tmp_path / "invalid.toml"
    config.write_text("not valid TOML")
    assert entry.main(["--config", str(config), "sync", "yesterday", "--write"]) == 1
    text = next((tmp_path / "logs").glob("*.log")).read_text()
    assert "Error:" in text and "Run finished: needs attention" in text and "Traceback" not in text
    assert "Run config: " + runlog.config_id(config) in text and "Run kind: nightly" in text
    assert "Write phase started." not in text


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_frozen_schedule_uses_app_directly(tmp_path, platform):
    plan = schedule.build_plan(tmp_path / "settings.toml", platform=platform, executable="/apps/autohours",
                               directory=tmp_path, home=tmp_path, uid=123, frozen=True)
    description = plan.describe()
    assert "-m autohours" not in description and "-B" not in description
    assert "yesterday" in description and "--write" in description
    assert "logs" in str(plan.log)


def test_windows_schedule_status_reads_disabled_flag(monkeypatch):
    monkeypatch.setattr(schedule, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(schedule.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0,
        stdout='<Task xmlns="urn:example"><Settings><Enabled>false</Enabled></Settings></Task>'))
    assert not schedule.enabled()
