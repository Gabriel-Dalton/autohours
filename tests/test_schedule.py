import os
from pathlib import Path
import plistlib
import shlex
from types import SimpleNamespace

import pytest

from autohours import schedule
from autohours.cli import main
from autohours.locking import writer_lock
from autohours.models import UserError
from autohours.setup import Prompts


def test_windows_command_uses_absolute_paths_and_quotes_spaces(tmp_path):
    path = tmp_path / "My Settings/autohours.toml"
    plan = schedule.build_plan(path, "06:15", platform="win32", executable=r"C:\Program Files\Python\python.exe")
    command = plan.commands[0]
    assert command[:5] == ["schtasks", "/Create", "/TN", "AutohoursDaily", "/SC"]
    assert command[command.index("/ST") + 1] == "06:15"
    action = command[command.index("/TR") + 1]
    assert action.startswith('"C:\\Program Files\\Python\\python.exe" -B -m autohours')
    assert '"' + str(path.resolve()) + '"' in action
    assert action.endswith("sync yesterday --write")
    assert "/IT" in command and "replaces" in plan.describe()


def test_launchd_plist_contains_arguments_time_and_private_logs(tmp_path):
    plan = schedule.build_plan(tmp_path / "a&b.toml", platform="darwin", executable="/opt/Python 3/bin/python3",
                               home=tmp_path, directory=tmp_path / "private", uid=123)
    data = plistlib.loads(plan.content.encode())
    assert data["ProgramArguments"] == ["/opt/Python 3/bin/python3", "-B", "-m", "autohours", "--config",
                                        str((tmp_path / "a&b.toml").resolve()), "sync", "yesterday", "--write"]
    assert data["StartCalendarInterval"] == {"Hour": 6, "Minute": 0}
    assert data["Umask"] == 0o077
    assert "EnvironmentVariables" not in data
    assert plan.path == tmp_path / "Library/LaunchAgents/local.autohours.daily.plist"
    assert plan.commands == [["launchctl", "bootstrap", "gui/123", str(plan.path)]]


def test_cron_preserves_other_jobs_replaces_own_and_escapes_paths(tmp_path):
    old = "# Personal jobs\n0 12 * * * echo keep\n0 4 * * * stale-job-command # autohours daily\n"
    config = tmp_path / "a '$(echo nope) 100%.toml"
    plan = schedule.build_plan(config, "07:30", platform="linux", executable="/opt/python 3/bin/python",
                               directory=tmp_path, crontab=old)
    assert plan.commands == [["crontab", "-"]]
    assert plan.stdin.startswith("# Personal jobs\n0 12 * * * echo keep\n30 7 * * * umask 077; ")
    assert "stale-job-command" not in plan.stdin and plan.stdin.count(schedule.MARKER) == 1
    assert r"100\%" in plan.stdin
    shell_command = plan.stdin.splitlines()[-1].split("umask 077; ", 1)[1].split(" >> ")[0].replace(r"\%", "%")
    assert shlex.split(shell_command)[0] == "XDG_CONFIG_HOME=" + str(tmp_path.parent)
    assert shlex.split(shell_command)[6] == str(config.resolve())
    assert "CLOCKIFY_API_KEY" not in plan.describe()


@pytest.mark.parametrize("value", ["6 AM", "24:00", "06:60", "-1:00", "6:0", "06:00\nrun"])
def test_invalid_schedule_time(value):
    with pytest.raises(ValueError):
        schedule.clock(value)


def test_schedule_declined_runs_no_commands(tmp_path, monkeypatch):
    monkeypatch.setattr(schedule, "sys", SimpleNamespace(platform="win32", executable="python.exe"))
    monkeypatch.setattr(schedule, "install", lambda *a: pytest.fail("Unapproved schedule"))
    replies = iter(["", "no"])
    output = []
    schedule.offer(tmp_path / "autohours.toml", Prompts(lambda _: next(replies), output=output.append))
    assert any("schtasks" in line and "06:00" in line for line in output)


def test_schedule_approved_uses_built_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(schedule, "sys", SimpleNamespace(platform="win32", executable="python.exe"))
    plans = []
    monkeypatch.setattr(schedule, "install", plans.append)
    replies = iter(["06:30", "back", "07:00", "yes"])
    schedule.offer(tmp_path / "autohours.toml", Prompts(lambda _: next(replies)))
    assert len(plans) == 1 and "07:00" in plans[0].commands[0]


def test_linux_remove_only_own_cron_line(monkeypatch):
    monkeypatch.setattr(schedule, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(schedule, "read_crontab", lambda: "0 0 * * * keep\n0 6 * * * ours # autohours daily\n")
    calls = []
    monkeypatch.setattr(schedule, "execute", lambda command, input=None: calls.append((command, input)))
    assert main(["schedule", "--remove"]) == 0
    assert calls == [(["crontab", "-"], "0 0 * * * keep\n")]


def test_windows_remove_uses_named_task_only(monkeypatch):
    monkeypatch.setattr(schedule, "sys", SimpleNamespace(platform="win32"))
    calls = []
    monkeypatch.setattr(schedule, "execute", lambda command: calls.append(command))
    schedule.remove()
    assert calls == [["schtasks", "/Delete", "/TN", "AutohoursDaily", "/F"]]


def test_mac_install_and_remove_do_not_run_real_launchctl(tmp_path, monkeypatch):
    monkeypatch.setattr(schedule, "sys", SimpleNamespace(platform="darwin", executable="/usr/bin/python3"))
    monkeypatch.setattr(schedule.os, "getuid", lambda: 123, raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    calls = []
    monkeypatch.setattr(schedule, "execute", lambda command, input=None: calls.append(command))
    plan = schedule.build_plan(tmp_path / "autohours.toml", home=tmp_path, directory=tmp_path / "private")
    schedule.install(plan)
    assert plistlib.loads(plan.path.read_bytes())["Label"] == schedule.LABEL
    assert calls == [["launchctl", "bootstrap", "gui/123", str(plan.path)]]
    assert plan.log.exists()
    schedule.remove()
    assert calls[-1] == ["launchctl", "bootout", "gui/123/local.autohours.daily"]
    assert not plan.path.exists()


def test_read_crontab_does_not_treat_permission_error_as_empty(monkeypatch):
    monkeypatch.setattr(schedule.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1, stderr="permission denied", stdout=""))
    with pytest.raises(UserError, match="No schedule was changed"):
        schedule.read_crontab()
    monkeypatch.setattr(schedule.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1, stderr="no crontab for fictional-user", stdout=""))
    assert schedule.read_crontab() == ""


def test_install_failure_is_friendly_and_no_real_scheduler(monkeypatch):
    monkeypatch.setattr(schedule.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1))
    with pytest.raises(UserError, match="could not update"):
        schedule.install(schedule.Plan([["schtasks", "/Create"]]))


def test_crontab_concurrent_edit_is_preserved(tmp_path, monkeypatch):
    plan = schedule.build_plan(tmp_path / "autohours.toml", platform="linux", directory=tmp_path, crontab="old\n")
    monkeypatch.setattr(schedule, "read_crontab", lambda: "new\n")
    monkeypatch.setattr(schedule, "execute", lambda *a: pytest.fail("Must not overwrite changed crontab"))
    with pytest.raises(UserError, match="changed after the preview"):
        schedule.install(plan)
    assert not (tmp_path / "schedule.log").exists()


def test_writer_lock_blocks_concurrent_sync_and_releases(tmp_path):
    config = tmp_path / "autohours.toml"
    with writer_lock(config):
        with pytest.raises(UserError, match="Another sync"):
            with writer_lock(config):
                pytest.fail("Second writer acquired the lock")
    with writer_lock(config):
        pass
