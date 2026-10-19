from datetime import datetime, timezone
from pathlib import Path
import re
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from autohours import cli, credentials
from autohours import setup as wizard
from autohours.config import load_config
from autohours.models import Activity, UserError
from autohours.pipeline import classify
from autohours.plugins import SOURCES


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 17, 12, tzinfo=timezone.utc).astimezone(tz)


class Services:
    def __init__(self):
        self.calls = []
        self.entries = []
        self.projects = [{"id": "p1", "name": "Acme Corp"}]
        self.project = {"name": "Acme Corp", "public": True, "billable": False,
                        "hourlyRate": {"amount": 5000, "currency": "CAD"}}
        self.window = {"timestamp": "2026-10-16T09:00:00Z", "duration": 3600,
                       "data": {"app": "Acme.App+", "title": "Acme launch [draft]"}}
        self.aw_up = True

    def request(self, http, method, path, body=None):
        self.calls.append((http.label, method, path, body))
        route = urlsplit(path).path
        if http.label == "ActivityWatch":
            if not self.aw_up:
                raise UserError("Cannot reach ActivityWatch.")
            if route == "/buckets/":
                return {"aw-watcher-window_fake": {}, "aw-watcher-afk_fake": {}}
            if "aw-watcher-window" in route:
                return [self.window]
            if "aw-watcher-afk" in route:
                return [{**self.window, "data": {"status": "not-afk"}}]
            raise AssertionError(path)
        assert http.label == "Clockify"
        if route == "/user":
            if http.headers.get("X-Api-Key") == "bad":
                raise UserError("Clockify returned HTTP 401.")
            return {"id": "u1"}
        if route == "/workspaces":
            return [{"id": "w1", "name": "Example workspace"}]
        if route == "/workspaces/w1":
            return {"hourlyRate": {"currency": "CAD"}}
        if route == "/workspaces/w1/projects":
            if method == "POST":
                self.projects.append({"id": "p2", "name": body["name"]})
                return self.projects[-1]
            return self.projects.copy()
        if route == "/workspaces/w1/projects/p1":
            if method == "PUT":
                self.project["billable"] = body["billable"]
                self.project["hourlyRate"] = {"amount": body["hourlyRate"]["amount"], "currency": "CAD"}
            return self.project.copy()
        if route == "/workspaces/w1/time-entries" and method == "POST":
            self.entries.append({"id": "entry1", "projectId": body["projectId"],
                                 "timeInterval": {"start": body["start"], "end": body["end"]}})
            return {"id": "entry1"}
        if route == "/workspaces/w1/user/u1/time-entries":
            return [] if "in-progress" in path else self.entries.copy()
        raise AssertionError((method, path, body))


@pytest.fixture
def services(monkeypatch, tmp_path):
    services = Services()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(wizard, "datetime", Clock)
    monkeypatch.setattr(cli, "datetime", Clock)
    monkeypatch.setattr(wizard, "detected_timezone", lambda: "UTC")
    monkeypatch.setattr(wizard.JsonHTTP, "request", lambda http, *a, **kw: services.request(http, *a, **kw))
    monkeypatch.setattr(wizard, "user_config_dir", lambda: tmp_path / "user")
    monkeypatch.setattr(wizard, "config_path", lambda explicit=None: Path(explicit) if explicit else tmp_path / "user/autohours.toml")
    return services


def run_setup(answers, path, secrets=(), add=False):
    answers, secrets = iter(answers), iter(secrets)
    transcript = []
    def read(prompt):
        transcript.append(prompt)
        return next(answers)
    def secret(prompt):
        transcript.append(prompt)
        return next(secrets)
    result = wizard.setup(str(path) if path else None, add, read, secret, transcript.append)
    assert list(answers) == []
    assert list(secrets) == []
    return result, "\n".join(transcript)


def agreement(billing="4", rate="", currency=""):
    return [billing, *([rate, currency] if billing == "1" else []), "0", "no", "1", ""]


def csv_answers(path):
    return ["yes", "2", str(path), "Acme Corp", "1", "Project work", *agreement(), "done"]


def test_csv_full_happy_path_and_no_regex_needed(tmp_path, services):
    path = tmp_path / "autohours.toml"
    csv = tmp_path / "times.csv"
    status, transcript = run_setup(csv_answers(csv) + ["yes", "yes", "yes", "no"], path)
    config = load_config(path)
    assert status == 0 and csv.exists()
    assert "private local window titles" in transcript
    assert "100.0%" in transcript
    assert config.projects[0].agreement["billing"] == "none"
    assert classify(config.projects, app="Acme.App+") == 0
    assert classify(config.projects, app="AcmeXApp") is None
    assert "Acme launch" not in csv.read_text()
    assert not any(method != "GET" for _, method, _, _ in services.calls)


def test_clockify_full_happy_path_rate_apply_and_key_privacy(tmp_path, services, monkeypatch, capsys):
    saved = []
    monkeypatch.setattr(wizard, "save_key", lambda key, output: (saved.append(key), monkeypatch.setenv("CLOCKIFY_API_KEY", key)))
    path = tmp_path / "autohours.toml"
    answers = ["yes", "1", "1", "Acme Corp", "2", "Acme", "1", "Project work",
               *agreement("1", "100", "CAD"), "done", "yes", "yes", "yes", "yes", "no"]
    status, transcript = run_setup(answers, path, ["synthetic-secret"])
    output = capsys.readouterr().out
    assert status == 0 and saved == ["synthetic-secret"]
    assert "synthetic-secret" not in path.read_text() + transcript + output
    assert "50.00 CAD/h -> 100.00 CAD/h" in output
    assert "confirmed" in output
    posts = [body for label, method, route, body in services.calls if method == "POST"]
    assert len(posts) == 1
    assert set(posts[0]) == {"start", "end", "description", "billable", "projectId"}
    assert posts[0]["projectId"] == "p1"


@pytest.mark.parametrize("stop", ["quit", KeyboardInterrupt, EOFError])
def test_quit_before_confirmation_writes_nothing(tmp_path, services, monkeypatch, stop):
    path = tmp_path / "autohours.toml"
    replies = iter(csv_answers(tmp_path / "times.csv"))
    def read(prompt):
        try:
            return next(replies)
        except StopIteration:
            if isinstance(stop, str):
                return stop
            raise stop
    monkeypatch.setattr(wizard, "save_key", lambda *a: pytest.fail("Unexpected credential write"))
    assert wizard.setup(str(path), input_fn=read) == 0
    assert not path.exists() and not (tmp_path / "times.csv").exists()
    assert not any(method != "GET" for _, method, _, _ in services.calls)


def test_back_revisits_previous_answer_and_discards_later_values(tmp_path, services):
    path = tmp_path / "autohours.toml"
    answers = ["yes", "2", str(tmp_path / "times.csv"), "Acme Corp", "1", "Old description", "back",
               "New description", *agreement(), "done", "yes", "no"]
    assert run_setup(answers, path)[0] == 0
    assert load_config(path).projects[0].description == "New description"


def test_existing_config_add_preserves_comments_and_settings(tmp_path, services):
    path = tmp_path / "autohours.toml"
    run_setup(csv_answers(tmp_path / "times.csv") + ["yes", "no"], path)
    original = path.read_text().replace('timezone = "UTC"', '# Keep this comment\ntimezone = "UTC"')
    path.write_text(original)
    answers = ["1", "Beta", "2", "launch", "Beta work", *agreement(), "done", "yes", "no"]
    run_setup(answers, path)
    assert path.read_text().startswith(original)
    cfg = load_config(path)
    assert [p.name for p in cfg.projects] == ["Acme Corp", "Beta"]
    assert cfg.destination["path"] == str(tmp_path / "times.csv")


def test_add_project_skips_timezone_destination_and_existing_choice(tmp_path, services):
    path = tmp_path / "autohours.toml"
    run_setup(csv_answers(tmp_path / "times.csv") + ["yes", "no"], path)
    answers = ["Beta", "2", "launch", "Beta work", *agreement(), "done", "yes", "no"]
    _, transcript = run_setup(answers, path, add=True)
    assert "Your system time zone" not in transcript and "Where should timesheets go" not in transcript
    assert len(load_config(path).projects) == 2


def test_existing_start_over_requires_save_and_quit_preserves_bytes(tmp_path, services):
    path = tmp_path / "autohours.toml"
    run_setup(csv_answers(tmp_path / "times.csv") + ["yes", "no"], path)
    original = path.read_bytes()
    run_setup(["2", *csv_answers(tmp_path / "other.csv"), "no"], path)
    assert path.read_bytes() == original
    run_setup(["3"], path)
    assert path.read_bytes() == original
    run_setup(["2", *csv_answers(tmp_path / "other.csv"), "yes", "no"], path)
    assert load_config(path).destination["path"] == str(tmp_path / "other.csv")


def test_default_location_and_current_folder_choice(tmp_path, services):
    run_setup(csv_answers(tmp_path / "times.csv") + ["1", "yes", "no"], None)
    assert (tmp_path / "user/autohours.toml").exists()
    (tmp_path / "user/autohours.toml").unlink()
    run_setup(csv_answers(tmp_path / "times.csv") + ["2", "yes", "no"], None)
    assert (tmp_path / "autohours.toml").exists()


def test_clockify_invalid_key_then_keep_valid_env(tmp_path, services, monkeypatch):
    monkeypatch.setattr(wizard, "save_key", lambda key, output: monkeypatch.setenv("CLOCKIFY_API_KEY", key))
    path = tmp_path / "autohours.toml"
    answers = ["yes", "1", "1", "Acme Corp", "1", "1", "Work", *agreement(), "done", "yes", "no"]
    _, output = run_setup(answers, path, ["bad", "synthetic-secret"])
    assert "could not be verified" in output
    monkeypatch.setenv("CLOCKIFY_API_KEY", "synthetic-secret")
    answers = ["2", "yes", "1", "yes", "1", "Acme Corp", "1", "1", "Work", *agreement(), "done", "yes", "no"]
    _, output = run_setup(answers, path)
    assert "Keep it?" in output and "(hidden)" not in output


def test_project_creation_deferred_until_confirmation(tmp_path, services, monkeypatch):
    monkeypatch.setattr(wizard, "save_key", lambda key, output: monkeypatch.setenv("CLOCKIFY_API_KEY", key))
    path = tmp_path / "autohours.toml"
    replies = ["yes", "1", "1", "Beta", "1", "2", "yes", "Work", *agreement(), "done"]
    run_setup(replies + ["quit"], path, ["synthetic-secret"])
    assert not path.exists() and not any(method == "POST" for _, method, _, _ in services.calls)
    run_setup(replies + ["yes", "no"], path, ["synthetic-secret"])
    posts = [body for _, method, route, body in services.calls if method == "POST"]
    assert posts == [{"name": "Beta", "isPublic": True, "billable": False, "color": "#2196F3"}]


def test_wait_retry_activitywatch_and_validation(tmp_path, services):
    services.aw_up = False
    replies = iter(["yes", *csv_answers(tmp_path / "times.csv"), "yes", "no"])
    def read(prompt):
        answer = next(replies)
        if "retry" in prompt:
            services.aw_up = True
        return answer
    assert wizard.setup(str(tmp_path / "autohours.toml"), input_fn=read) == 0
    assert list(replies) == []


def test_rules_escape_titles_and_domains_and_reject_unrelated_keyword(event, origin):
    activity = Activity([event(0, 20, app="Editor+", title="Acme [work]")], [event(0, 20, status="not-afk")],
                        [event(0, 20, title="Acme [work]", url="https://acme.example/path?private=secret")])
    end = activity.windows[0].end
    items = wizard.activity_items(activity, origin, end)
    replies = iter(["1 2 3", "unrelated", "[work]"])
    p = wizard.Prompts(lambda _: next(replies))
    rules = wizard.picked_rules(p, items, "Acme")
    assert re.search(rules["title"][0], "Acme [work]")
    assert not re.search(rules["title"][0], "work")
    assert re.search(rules["app"][0], "Editor+")
    assert re.search(rules["url"][0], "https://acme.example/path")
    assert not re.search(rules["url"][0], "https://acme.example.evil/path")
    assert "private" not in str(rules)


def test_doctor_failure_stops_before_any_write(tmp_path, services, monkeypatch):
    class Source:
        def check(self):
            raise UserError("AFK watcher unavailable")
    monkeypatch.setitem(SOURCES, "activitywatch", lambda cfg: Source())
    path = tmp_path / "autohours.toml"
    with pytest.raises(UserError, match="check needs attention"):
        run_setup(csv_answers(tmp_path / "times.csv") + ["yes"], path)
    assert path.exists() and not (tmp_path / "times.csv").exists()


def test_config_changed_during_questions_is_not_overwritten(tmp_path, services):
    path = tmp_path / "autohours.toml"
    replies = iter(csv_answers(tmp_path / "times.csv") + ["yes"])
    def read(prompt):
        if "Save these settings" in prompt:
            path.write_text("Changed elsewhere")
        return next(replies)
    with pytest.raises(UserError, match="changed during setup"):
        wizard.setup(str(path), input_fn=read)
    assert path.read_text() == "Changed elsewhere"


def test_agreement_questions_validate_and_keep_exact_choices():
    replies = iter(["1", "nan", "125.50", "badcurrency", "cad", "-1", "5", "yes", "3", "2", "40"])
    policy = wizard.ask_agreement(wizard.Prompts(lambda _: next(replies)))
    assert policy == {"billing": "hourly", "rate": 125.5, "currency": "CAD", "count_breaks_up_to_minutes": 5,
                      "count_calls_when_away": True, "round_to_minutes": 15, "rounding": "up", "monthly_cap_hours": 40}
    replies = iter(["3", "0", "no", "1", ""])
    assert wizard.ask_agreement(wizard.Prompts(lambda _: next(replies))) == {
        "billing": "retainer", "count_breaks_up_to_minutes": 0, "count_calls_when_away": False, "round_to_minutes": 0, "rounding": "nearest"}


def test_key_save_windows_does_not_echo_and_failure_is_redacted(monkeypatch):
    monkeypatch.setattr(credentials, "sys", SimpleNamespace(platform="win32"))
    calls, output = [], []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(credentials.subprocess, "run", run)
    credentials.save_key("synthetic-secret", output.append)
    assert calls[0][0] == ["setx", "CLOCKIFY_API_KEY", "synthetic-secret"]
    assert calls[0][1]["capture_output"]
    assert credentials.read_key() == "synthetic-secret"
    assert "synthetic-secret" not in str(output)
    monkeypatch.setattr(credentials.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1, stderr="synthetic-secret"))
    with pytest.raises(UserError) as exc:
        credentials.save_key("synthetic-secret")
    assert "synthetic-secret" not in str(exc.value)


@pytest.mark.skipif(__import__("os").name == "nt", reason="POSIX file permissions")
def test_key_file_permissions_env_priority_and_removal(tmp_path, monkeypatch):
    monkeypatch.setattr(credentials, "sys", SimpleNamespace(platform="linux"))
    credentials.save_key("synthetic-secret")
    path = credentials.credential_path()
    assert path.stat().st_mode & 0o777 == 0o600
    monkeypatch.delenv("CLOCKIFY_API_KEY")
    assert credentials.read_key() == "synthetic-secret"
    monkeypatch.setenv("CLOCKIFY_API_KEY", "env-secret")
    assert credentials.read_key() == "env-secret"
    monkeypatch.delenv("CLOCKIFY_API_KEY")
    path.chmod(0o644)
    with pytest.raises(UserError, match="permissions 600"):
        credentials.read_key()
    path.unlink()
    assert credentials.read_key() == ""
