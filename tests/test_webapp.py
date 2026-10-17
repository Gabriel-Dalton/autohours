from datetime import datetime, timezone
import errno
from email.message import Message
import io
import json
from pathlib import Path
import socket
import threading
import tomllib
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import build_opener, ProxyHandler, Request

import pytest

from autohours import desktop, runlog, setup, webapp
from autohours.models import UserError
from test_setup import Clock, csv_answers, run_setup, services


CONNECT = socket.socket.connect


@pytest.fixture
def app(tmp_path, services, monkeypatch):
    monkeypatch.setattr(webapp, "datetime", Clock)
    monkeypatch.setattr(desktop, "nightly_status", lambda: "Off")
    monkeypatch.setattr(runlog, "log_directory", lambda: tmp_path / "logs")
    value = desktop.Session(tmp_path / "web.toml")
    value.now = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
    return webapp.Application(value)


@pytest.fixture
def server_factory(app, monkeypatch):
    servers = []
    ports = set()

    def local_only(sock, address):
        assert address[0] == "127.0.0.1" and address[1] in ports, "Tests must not contact real destinations"
        return CONNECT(sock, address)

    monkeypatch.setattr(socket.socket, "connect", local_only)

    def make(**kwargs):
        try:
            server = webapp.Server(app.session, **kwargs)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EPERM) or getattr(exc, "winerror", None) == 10013:
                pytest.skip("This environment does not permit binding a localhost socket")
            raise
        ports.add(server.server_port)
        server.app = app
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        return server, thread

    yield make
    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def http(server, path, data=None, method=None, headers=None, token=True):
    headers = {"Content-Type": "application/json", **(headers or {})}
    if token:
        headers.setdefault("X-Autohours-Token", server.token)
    request = Request(server.origin + path, data=None if data is None else json.dumps(data).encode(),
                      method=method or ("GET" if data is None else "POST"), headers=headers)
    opener = build_opener(ProxyHandler({}))
    try:
        response = opener.open(request, timeout=3)
    except HTTPError as exc:
        response = exc
    with response:
        body = response.read()
        value = json.loads(body) if response.headers.get_content_type() == "application/json" else body
        return response.status, value, response.headers


@pytest.fixture(params=["direct", "http"])
def call(request, app, server_factory):
    if request.param == "http":
        server, _ = server_factory()

        def invoke(path, data=None, method=None):
            status, result, _ = http(server, "/api/" + path, data, method)
            if status != 200:
                raise webapp.InputError(result["error"], result.get("field"))
            return result
        return invoke

    def invoke(path, data=None, method=None):
        parsed = urlsplit("/api/" + path)
        return app.clean(app.dispatch(method or ("GET" if data is None else "POST"), parsed.path,
                                      data or {}, parse_qs(parsed.query)))
    return invoke


def csv_setup(call, tmp_path):
    call("timezone", {"timezone": "UTC"})
    assert call("activitywatch/check", {})["running"]
    call("destination", {"type": "csv", "path": str(tmp_path / "times.csv")})
    items = call("activity")["items"]
    picked = next(i["id"] for i in items if i["kind"] == "App")
    call("projects", {"projects": [{"name": "Acme Corp", "description": "Project work", "items": [picked]}]})
    assert call("coverage")["coverage"] == 100
    call("agreements", {"agreements": [{"billing": "none"}]})
    call("save", {})


def test_csv_api_matches_text_wizard(call, app, tmp_path, services):
    csv_setup(call, tmp_path)
    status, _ = run_setup(csv_answers(tmp_path / "times.csv") + ["yes", "no"], tmp_path / "wizard.toml")
    assert status == 0
    assert tomllib.loads(app.session.path.read_text()) == tomllib.loads((tmp_path / "wizard.toml").read_text())
    assert not (tmp_path / "times.csv").exists()
    assert all(method == "GET" for _, method, _, _ in services.calls)
    assert all(check["ok"] for check in call("doctor")["checks"])
    review = call("review?day=2026-10-16")
    assert review["hours"] == 1 and review["entries"][0]["project"] == "Acme Corp"
    assert "Acme launch" not in json.dumps(review)


def test_write_requires_fresh_preview_and_literal_confirmation(call, app, tmp_path):
    csv_setup(call, tmp_path)
    for confirm in (None, False, "true", 1, True):
        with pytest.raises(webapp.InputError, match="confirm"):
            call("write", {"day": "2026-10-16", "confirm": confirm})
    preview = call("write/preview", {"day": "2026-10-16"})
    assert "Would create 1" in preview["text"]
    assert not (tmp_path / "times.csv").exists()
    with pytest.raises(webapp.InputError):
        call("write", {"day": "2026-10-15", "confirm": True, "preview": preview["preview"]})
    result = call("write", {"day": "2026-10-16", "confirm": True, "preview": preview["preview"]})
    assert "Wrote 1 entries, 1.00 h" in result["message"]
    assert "Acme launch" not in (tmp_path / "times.csv").read_text()
    with pytest.raises(webapp.InputError):
        call("write", {"day": "2026-10-16", "confirm": True, "preview": preview["preview"]})
    again = call("write/preview", {"day": "2026-10-16"})
    assert "would skip 1" in again["text"]


def test_changed_settings_invalidate_write_preview(call, app, tmp_path):
    csv_setup(call, tmp_path)
    preview = call("write/preview", {"day": "2026-10-16"})
    call("agreements", {"agreements": [{"billing": "hourly", "rate": "100", "currency": "CAD"}]})
    with pytest.raises(webapp.InputError):
        call("write", {"day": "2026-10-16", "confirm": True, "preview": preview["preview"]})
    assert not (tmp_path / "times.csv").exists()


def test_clockify_key_never_leaks_and_single_workspace_is_selected(call, app, tmp_path, monkeypatch, services):
    secret = "synthetic-clockify-secret"
    monkeypatch.setattr(setup, "save_key", lambda key, output: monkeypatch.setenv("CLOCKIFY_API_KEY", key))
    call("destination", {"type": "clockify"})
    responses = [call("clockify/key", {"key": secret}), call("clockify/workspaces"), call("state")]
    assert responses[0]["single_workspace"] and responses[0]["currency"] == "CAD"
    assert app.session.raw["destination"]["workspace"] == "w1"
    call("activitywatch/check", {})
    call("activity")
    call("projects", {"projects": [{"name": "Acme Corp", "description": "Development", "items": [0], "target": "p1"}]})
    call("agreements", {"agreements": [{"billing": "hourly", "rate": "100", "currency": "CAD"}]})
    responses.append(call("save", {}))
    responses.append(call("review?day=2026-10-16"))
    rates = call("rates")
    with pytest.raises(webapp.InputError):
        call("rates/apply", {"confirm": True})
    responses.append(call("rates/apply", {"confirm": True, "preview": rates["preview"]}))
    assert any("confirmed" in line for line in responses[-1]["messages"])
    assert secret not in json.dumps(responses) + app.session.path.read_text()
    app.session.spaces[0]["name"] = secret
    assert secret not in json.dumps(call("clockify/workspaces"))
    assert not any(method == "POST" for _, method, _, _ in services.calls)


def test_validation_names_field_and_is_transactional(call, app, tmp_path):
    with pytest.raises(webapp.InputError) as error:
        call("timezone", {"timezone": "Imaginary/City"})
    assert error.value.field == "timezone"
    call("activitywatch/check", {})
    call("activity")
    with pytest.raises(webapp.InputError) as error:
        call("projects", {"projects": [{"name": "Acme Corp", "description": "Work", "items": []}]})
    assert error.value.field == "project-0" and not app.session.raw["projects"]
    call("projects", {"projects": [{"name": "Acme Corp", "description": "Work", "items": [0]}]})
    for fields, field in (({}, "billing-0"), ({"billing": "hourly", "rate": "oops"}, "rate-0"),
                          ({"billing": "hourly", "currency": "dollars"}, "currency-0")):
        with pytest.raises(webapp.InputError) as error:
            call("agreements", {"agreements": [fields]})
        assert error.value.field == field
    assert app.session.raw["projects"][0]["agreement"] == {}


def test_project_edits_preserve_unseen_patterns_and_agreements(call, app, tmp_path):
    csv_setup(call, tmp_path)
    app.session.raw["projects"][0]["title"] = ["Acme shared"]
    app.session.raw["projects"][0]["agreement"]["call_apps"] = ["CustomCall"]
    rows = call("activity")["projects"]
    rows.append({"name": "Globex", "description": "Work", "items": [], "id": None})
    rows = call("projects", {"projects": rows, "validate": False})["projects"]
    rows[0]["name"] = "Acme Corp renamed"
    rows.reverse()
    call("projects", {"projects": rows, "validate": False})
    assert app.session.raw["projects"][1]["title"] == ["Acme shared"]
    assert app.session.raw["projects"][1]["agreement"]["call_apps"] == ["CustomCall"]
    call("projects", {"projects": [], "validate": False})
    assert not app.session.raw["projects"]


def test_schedule_requires_matching_preview_and_confirm(call, app, tmp_path, monkeypatch):
    csv_setup(call, tmp_path)
    installed = []
    monkeypatch.setattr(webapp.schedule, "read_crontab", lambda: "")
    monkeypatch.setattr(webapp.schedule, "install", installed.append)
    monkeypatch.setattr(webapp.schedule, "remove", lambda: installed.append("removed"))
    plan = call("schedule/plan?at=06:00")
    assert "06:00" in plan["at"] and "yesterday" in plan["text"]
    with pytest.raises(webapp.InputError):
        call("schedule", {"confirm": True, "preview": "stale"})
    assert not installed
    call("schedule", {"confirm": True, "preview": plan["preview"]})
    assert len(installed) == 1
    with pytest.raises(webapp.InputError):
        call("schedule", {}, "DELETE")
    call("schedule", {"confirm": True}, "DELETE")
    assert installed[-1] == "removed"


def test_reset_discards_unsaved_project_changes(call, app, tmp_path):
    csv_setup(call, tmp_path)
    rows = call("activity")["projects"]
    rows[0]["description"] = "Unfinished draft"
    call("projects", {"projects": rows})
    call("reset", {})
    assert call("state")["projects"][0]["description"] == "Project work"


def test_partial_write_consumes_confirmation_and_logs_failure(call, app, tmp_path, monkeypatch):
    csv_setup(call, tmp_path)
    preview = call("write/preview", {"day": "2026-10-16"})
    monkeypatch.setattr(app.session, "command", lambda *args: (_ for _ in ()).throw(UserError("Write interrupted")))
    with pytest.raises(webapp.InputError, match="Some entries may already be saved"):
        call("write", {"day": "2026-10-16", "confirm": True, "preview": preview["preview"]})
    with pytest.raises(webapp.InputError, match="confirm"):
        call("write", {"day": "2026-10-16", "confirm": True, "preview": preview["preview"]})
    assert "needs attention" in runlog.last_summary(tmp_path / "logs")


def test_changed_remote_rates_need_another_confirmation(call, app, tmp_path, monkeypatch):
    csv_setup(call, tmp_path)
    differences = ["Acme Corp: 50 CAD/h to 100 CAD/h"]
    applied = []
    monkeypatch.setattr(app.session, "rates", lambda apply=False: (applied.append(True) if apply else None) or (list(differences), False))
    preview = call("rates")
    differences[0] = "Acme Corp: 75 CAD/h to 100 CAD/h"
    with pytest.raises(webapp.InputError, match="changed"):
        call("rates/apply", {"confirm": True, "preview": preview["preview"]})
    assert not applied


def test_activitywatch_failure_is_plain_and_multiple_computers_need_choice(call, app, services, monkeypatch):
    services.aw_up = False
    result = call("activitywatch/check", {})
    assert not result["running"] and "AFK" not in result["message"]
    services.aw_up = True
    monkeypatch.setattr(app.session, "hosts", lambda: ["Acme laptop", "Globex laptop"])
    result = call("activitywatch/check", {})
    assert not result["running"] and len(result["hosts"]) == 2
    assert "Choose" in result["message"]


def test_switch_to_spreadsheet_does_not_assume_clockify_currency(call, app, tmp_path):
    call("destination", {"type": "clockify"})
    assert call("clockify/key", {"key": "synthetic-secret"})["currency"] == "CAD"
    call("destination", {"type": "csv", "path": str(tmp_path / "times.csv")})
    assert call("state")["currency"] == ""


@pytest.mark.parametrize("headers, token", [({}, False), ({"X-Autohours-Token": "wrong"}, True),
    ({"Host": "localhost:9000"}, True), ({"Origin": "https://foreign.example"}, True), ({"Origin": "null"}, True)])
def test_rejects_missing_token_wrong_host_and_foreign_origin(server_factory, headers, token):
    server, _ = server_factory()
    status, body, response_headers = http(server, "/api/state", headers=headers, token=token)
    assert status == 403 and "error" in body
    assert response_headers["Cache-Control"] == "no-store"


def test_bootstrap_is_single_use_and_not_an_api_token(server_factory):
    server, _ = server_factory()
    code = server.bootstrap
    assert server.url == server.origin + "/#b=" + code
    for wrong in ("wrong", "", None, 42, {}, "\ud800"):
        assert http(server, "/api/session", {"bootstrap": wrong}, token=False)[0] == 403
    for headers in ({"Host": "foreign.example"}, {"Origin": "https://foreign.example"}):
        assert http(server, "/api/session", {"bootstrap": code}, headers=headers, token=False)[0] == 403
    assert http(server, "/api/state", headers={"X-Autohours-Token": code})[0] == 403
    status, result, _ = http(server, "/api/session", {"bootstrap": code}, token=False)
    assert status == 200 and result == {"token": server.token}
    assert server.bootstrap is None
    assert http(server, "/api/session", {"bootstrap": code}, token=False)[0] == 403
    assert http(server, "/api/state", headers={"X-Autohours-Token": result["token"]})[0] == 200


def test_expired_bootstrap_is_rejected(server_factory):
    server, _ = server_factory(first_timeout=300)
    server.started -= 121
    assert http(server, "/api/session", {"bootstrap": server.bootstrap}, token=False)[0] == 403


def test_concurrent_bootstrap_redemption_has_one_winner(server_factory):
    server, _ = server_factory()
    code = server.bootstrap
    barrier = threading.Barrier(2)
    results = []

    def redeem():
        barrier.wait(timeout=2)
        results.append(server.redeem_bootstrap(code))

    threads = [threading.Thread(target=redeem) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
    assert sorted(results) == [False, True]


@pytest.mark.parametrize("path", ["/api/state", "/", "/api/session", "/missing"])
@pytest.mark.parametrize("failure_at", [1, 2])
def test_disconnected_response_is_silent_and_never_retried(server_factory, capsys, path, failure_at):
    server, _ = server_factory()
    writes, responses = [], []

    class DisconnectedWriter:
        def write(self, body):
            writes.append(body)
            if len(writes) == failure_at:
                raise ConnectionAbortedError(10053, "Synthetic disconnect")

    handler = object.__new__(webapp.Handler)
    handler.server = server
    handler.command = "POST" if path == "/api/session" else "GET"
    handler.path = path
    handler.request_version = "HTTP/1.1"
    handler.requestline = handler.command + " " + path + " HTTP/1.1"
    handler.headers = Message()
    handler.headers["Host"] = server.host
    handler.headers["X-Autohours-Token"] = server.token
    body = json.dumps({"bootstrap": server.bootstrap}).encode()
    handler.headers["Content-Type"] = "application/json"
    handler.headers["Content-Length"] = str(len(body))
    handler.rfile = io.BytesIO(body)
    handler.wfile = DisconnectedWriter()
    original = handler.send_response

    def send_response(status):
        responses.append(status)
        original(status)

    handler.send_response = send_response
    handler.handle_request()
    assert len(responses) == 1
    assert len(writes) == failure_at
    assert handler.close_connection
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("kind", ["abort", "reset", "pipe", 10053, 10054, "unexpected"])
def test_server_errors_are_silent_or_privately_logged(server_factory, kind, capsys, tmp_path):
    server, _ = server_factory()
    if isinstance(kind, int):
        error = OSError("Synthetic disconnect")
        error.winerror = kind
    else:
        error = {"abort": ConnectionAbortedError, "reset": ConnectionResetError,
                 "pipe": BrokenPipeError, "unexpected": RuntimeError}[kind](server.token)
    try:
        raise error
    except Exception:
        server.handle_error(None, ("127.0.0.1", 1234))
    assert capsys.readouterr().err == ""
    logs = list((tmp_path / "logs").glob("*.log"))
    assert bool(logs) == (kind == "unexpected")
    for log in logs:
        text = log.read_text()
        assert "RuntimeError" in text and server.token not in text


def test_launch_and_error_logs_never_expose_token(server_factory, monkeypatch, capsys, tmp_path):
    server, _ = server_factory()
    server.shutdown()
    monkeypatch.setattr(webapp, "Server", lambda session: server)
    monkeypatch.setattr(webapp.desktop, "Session", lambda explicit: server.app.session)
    monkeypatch.setattr(server, "serve_forever", lambda: None)
    commands = []
    monkeypatch.setattr(webapp, "browser_command", lambda url: ["synthetic-browser", "--app=" + url])
    monkeypatch.setattr(webapp.subprocess, "Popen", lambda command, **kwargs: commands.append(command))
    assert webapp.launch() == 0
    output = capsys.readouterr()
    assert server.url in output.out and not output.err
    assert commands == [["synthetic-browser", "--app=" + server.url]]
    assert server.token not in output.out + repr(commands)
    webapp.log_event(server.clean_error("Synthetic error " + server.token + " " + server.bootstrap))
    log = next((tmp_path / "logs").glob("*.log")).read_text()
    assert server.token not in log and server.bootstrap not in log


def test_static_files_headers_and_traversal(server_factory):
    server, _ = server_factory()
    for path, mime in (("/", "text/html"), ("/app.js", "text/javascript"), ("/app.css", "text/css")):
        status, body, headers = http(server, path, token=False)
        assert status == 200 and body
        assert headers.get_content_type() == mime
        assert headers["Content-Security-Policy"] == webapp.CSP
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Cache-Control"] == "no-store"
        assert headers["Referrer-Policy"] == "no-referrer"
    for path in ("/../webapp.py", "/%2e%2e/webapp.py", "/%252e%252e/webapp.py", "/web/%2e%2e/app.js", "/..%5cwebapp.py"):
        assert http(server, path)[0] == 400
    assert http(server, "/credentials")[0] == 404
    assert http(server, "/", headers={"Origin": "https://foreign.example"})[0] == 403
    assert http(server, "/api/state", headers={"Origin": server.origin})[0] == 200
    assert http(server, "/api/quit", {}, token=False)[0] == 403
    assert http(server, "/api/heartbeat", {}, headers={"X-Autohours-Token": "wrong"})[0] == 403


def test_errors_are_json_with_field_names_and_private_traceback(server_factory, app, monkeypatch, tmp_path):
    server, _ = server_factory()
    status, result, _ = http(server, "/api/agreements", {"agreements": [{}]})
    assert status == 400 and result["field"] == "billing-0"
    secret = "synthetic-private-key"
    app.secrets.add(secret)
    monkeypatch.setattr(app, "state", lambda: (_ for _ in ()).throw(RuntimeError(secret)))
    status, result, _ = http(server, "/api/state")
    assert status == 500 and secret not in json.dumps(result) and "Traceback" not in json.dumps(result)
    log = next((tmp_path / "logs").glob("*.log")).read_text()
    assert "Traceback" in log and secret not in log


@pytest.mark.parametrize("heartbeat", [False, True])
def test_heartbeat_timeout_stops_server(server_factory, heartbeat):
    server, thread = server_factory(first_timeout=.4, heartbeat_timeout=.15)
    if heartbeat:
        assert http(server, "/api/heartbeat", {})[0] == 200
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_quit_stops_server_and_heartbeat_does_not_wait_for_work(server_factory, app):
    server, thread = server_factory()
    with app.lock:
        assert http(server, "/api/heartbeat", {})[0] == 200
        assert http(server, "/api/state")[0] == 409
        assert http(server, "/api/write", {"confirm": True})[0] == 409
    assert http(server, "/api/quit", {})[0] == 200
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_writes_cannot_overlap_and_heartbeat_stays_responsive(server_factory, app, tmp_path):
    server, _ = server_factory()
    started, release = threading.Event(), threading.Event()
    original = app.dispatch

    def dispatch(method, path, data, query):
        if path == "/api/write":
            started.set()
            assert release.wait(timeout=3)
            return {"ok": True}
        return original(method, path, data, query)

    app.dispatch = dispatch
    results = []
    thread = threading.Thread(target=lambda: results.append(http(server, "/api/write", {})))
    thread.start()
    try:
        assert started.wait(timeout=2)
        assert http(server, "/api/write", {})[0] == 409
        assert http(server, "/api/heartbeat", {})[0] == 200
    finally:
        release.set()
        thread.join(timeout=2)
    assert results[0][0] == 200


@pytest.mark.parametrize("platform, executable", [
    ("win32", "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    ("darwin", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ("linux", "/usr/bin/chromium")])
def test_browser_discovery_and_flags(platform, executable, monkeypatch, tmp_path):
    expected = Path(executable)
    monkeypatch.setattr(Path, "is_file", lambda path: path == expected)
    monkeypatch.setattr(webapp.shutil, "which", lambda name: executable if name == "chromium" else None)
    url = "http://127.0.0.1:12345/#synthetic-launch-token"
    command = webapp.browser_command(url, platform, {"ProgramFiles(x86)": "C:/Program Files (x86)", "ProgramFiles": "C:/Program Files"}, tmp_path / "window")
    assert command == [str(expected), "--app=" + url, "--user-data-dir=" + str(tmp_path / "window"),
                       "--window-size=1100,780", "--no-first-run", "--no-default-browser-check"]


def test_browser_preference_and_fallbacks(monkeypatch):
    monkeypatch.setattr(Path, "is_file", lambda path: True)
    assert "msedge.exe" in webapp.browser_command("local", "win32", {"ProgramFiles": "C:/Program Files"})[0]
    monkeypatch.setattr(Path, "is_file", lambda path: False)
    monkeypatch.setattr(webapp.shutil, "which", lambda name: None)
    assert webapp.browser_command("local", "win32", {}) is None
    assert webapp.browser_command("local", "linux") is None
    assert webapp.browser_command("local", "darwin") == ["open", "local"]


def test_open_window_falls_back_without_launching_browser(monkeypatch):
    opened = []
    monkeypatch.setattr(webapp, "browser_command", lambda url: ["synthetic-browser", "--app=" + url])
    monkeypatch.setattr(webapp.subprocess, "Popen", lambda *a, **kw: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(webapp.webbrowser, "open", opened.append)
    webapp.open_window("http://127.0.0.1:1234/#synthetic")
    assert opened == ["http://127.0.0.1:1234/#synthetic"]


def test_recent_run_summary_uses_written_hours_without_private_output(tmp_path):
    (tmp_path / "2026-10-17.log").write_text("Run started: 2026-10-17T06:00:00\nPrivate local activity\nWrote 5 entries, 2.75 h.\nRun finished: success\n")
    assert runlog.last_summary(tmp_path, Clock.now().date()) == "Today at 6:00 AM: wrote 5 entries, 2 h 45 min."


def test_review_summary_reports_minutes_threshold_and_hourly_amount(call, app, tmp_path, monkeypatch, event):
    from autohours.models import Activity
    from autohours.pipeline import build
    csv_setup(call, tmp_path)
    app.session.raw["blocks"] = {"min_block_minutes": 5}
    call("agreements", {"agreements": [{"billing": "hourly", "rate": "100", "currency": "CAD"}]})
    cfg = app.session.config()
    activity = Activity([event(0, 139, app="Acme.App+"), event(150, 154, app="Acme.App+"),
                         event(170, 560, app="Unassigned")], [event(0, 560, status="not-afk")])
    result = build(activity, cfg.projects, cfg.blocks, event(0, 560).start, event(0, 560).end, cfg.timezone)
    monkeypatch.setattr(app.session, "review", lambda day: (cfg, result))
    summary = call("review?day=2026-10-16")
    assert summary["minutes"] == summary["entries"][0]["minutes"] == 139
    assert summary["unmatched_minutes"] == 390
    assert summary["short_piece_minutes"] == 4
    assert summary["minimum_minutes"] == 5
    assert summary["amounts"] == ["231.67 CAD"]


def test_rounding_reduction_is_not_reported_as_a_short_piece(call, app, tmp_path, monkeypatch, event):
    from autohours.models import Activity
    from autohours.pipeline import build
    csv_setup(call, tmp_path)
    call("agreements", {"agreements": [{"billing": "hourly", "round_to_minutes": "6"}]})
    cfg = app.session.config()
    activity = Activity([event(0, 14, app="Acme.App+")], [event(0, 14, status="not-afk")])
    result = build(activity, cfg.projects, cfg.blocks, event(0, 14).start, event(0, 14).end, cfg.timezone)
    monkeypatch.setattr(app.session, "review", lambda day: (cfg, result))
    summary = call("review?day=2026-10-16")
    assert summary["minutes"] == 12 and summary["short"] == 2
    assert summary["short_piece_minutes"] == summary["unmatched_minutes"] == 0
    assert summary["amounts"] == []

    # A piece longer than the minimum can round down to zero. Do not call
    # that time "under 10 min" either; the calculation disclosure covers it.
    call("agreements", {"agreements": [{"billing": "hourly", "round_to_minutes": "30"}]})
    cfg = app.session.config()
    result = build(activity, cfg.projects, cfg.blocks, event(0, 14).start, event(0, 14).end, cfg.timezone)
    summary = call("review?day=2026-10-16")
    assert summary["minutes"] == summary["short_piece_minutes"] == 0


def test_review_cache_invalidation_and_fresh_today(call, app, tmp_path, services, monkeypatch):
    from autohours import activitywatch
    monkeypatch.setattr(activitywatch, "datetime", Clock)
    csv_setup(call, tmp_path)
    services.calls.clear()
    call("review?day=2026-10-16")
    assert len(services.calls) == 5
    call("review?day=2026-10-16")
    assert len(services.calls) == 5
    call("doctor")  # Shares cached discovery, not another bucket request.
    assert len(services.calls) == 5
    call("review?day=2026-10-17")
    call("review?day=2026-10-17")
    assert len(services.calls) == 13
    call("agreements", {"agreements": [{"billing": "hourly", "rate": "50", "currency": "CAD"}]})
    call("review?day=2026-10-16")
    assert len(services.calls) == 18
    # Also catch direct Session edits, including time zone, host, and web settings.
    app.session.raw["timezone"] = "America/Vancouver"
    call("review?day=2026-10-16")
    assert len(services.calls) == 23
    call("reset", {})
    call("review?day=2026-10-16")
    assert len(services.calls) == 28


def test_read_requests_overlap_but_mutations_remain_exclusive(server_factory, app):
    server, _ = server_factory()
    started = {route: threading.Event() for route in ("review", "doctor")}
    release = threading.Event()
    original = app.dispatch
    def dispatch(method, path, data, query):
        route = path.removeprefix("/api/")
        if route in started:
            started[route].set()
            assert release.wait(timeout=3)
            return {"ok": True}
        return original(method, path, data, query)
    app.dispatch = dispatch
    results = []
    threads = [threading.Thread(target=lambda route=route: results.append(http(server, "/api/" + route))) for route in started]
    for thread in threads:
        thread.start()
    try:
        assert all(event.wait(timeout=2) for event in started.values())
        assert http(server, "/api/state")[0] == 200
        assert http(server, "/api/timezone", {"timezone": "UTC"})[0] == 409
        assert http(server, "/api/write", {})[0] == 409
    finally:
        release.set()
        for thread in threads:
            thread.join(timeout=2)
    assert len(results) == 2 and all(result[0] == 200 for result in results)
    assert app.readers == 0


@pytest.mark.parametrize("error, phase, expected", [
    ("Cannot reach Clockify.", False, "could not reach Clockify. Nothing was written."),
    ("Cannot reach Clockify.", True, "could not reach Clockify. Some entries may have been written."),
    ("Cannot reach ActivityWatch.", False, "could not reach ActivityWatch. Nothing was written."),
    ("Clockify returned HTTP 401.", False, "Clockify rejected access. Nothing was written."),
    ("Unrecognized private detail", False, "needs attention. Nothing was written."),
])
def test_nightly_failure_summary_is_scoped_and_private(tmp_path, error, phase, expected):
    config = tmp_path / "settings.toml"
    marker = "Run config: " + runlog.config_id(config)
    text = ("Run started: 2026-10-16T06:00:00\n" + marker + "\nRun kind: nightly\n"
            + ("Write phase started.\n" if phase else "") + "Error: " + error + "\nRun finished: needs attention\n")
    # Newer manual/unscoped/other-config records must not mask this run.
    text += "Run started: 2026-10-17T06:00:00\nRun config: other\nRun kind: nightly\nRun finished: success\n"
    text += "Run started: 2026-10-17T07:00:00\n" + marker + "\nRun kind: manual\nRun finished: success\n"
    text += "Run started: 2026-10-17T08:00:00\nRun finished: success\n"
    (tmp_path / "2026-10-17.log").write_text(text)
    summary = runlog.last_summary(tmp_path, Clock.now().date(), config, nightly_only=True)
    assert summary.startswith("Friday, October 16 at 6:00 AM: ")
    assert expected in summary and "private detail" not in summary
    assert runlog.last_summary(tmp_path, config=tmp_path / "another.toml", nightly_only=True).startswith("Not run yet.")


def test_state_only_shows_nightly_runs_for_current_config(call, app, tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "2026-10-16.log").write_text("Run started: 2026-10-16T06:00:00\nRun config: " + runlog.config_id(app.session.path)
        + "\nRun kind: nightly\n" + "Private window title\n" * 1000 + "Wrote 0 entries, 0.00 h.\nRun finished: success\n")
    assert "wrote 0 entries, 0 min" in call("state")["last_run"]
    assert "Private" not in call("state")["last_run"]


@pytest.mark.parametrize("raw, expected", [("Whats App.Root", "WhatsApp"), ("WhatsApp.Root.exe", "WhatsApp"),
    ("msedge.exe", "Microsoft Edge"), ("SomeEditor.app", "Some Editor")])
def test_friendly_activity_labels_do_not_change_rules(raw, expected):
    assert desktop.activity_label("app", raw).startswith(expected + "  ")
    assert setup.item_rule("app", raw).startswith("^")


def test_icon_generator_remains_independent_and_reproducible(tmp_path):
    import runpy
    root = Path(__file__).resolve().parents[1]
    module = runpy.run_path(str(root / "packaging/generate_icons.py"))
    module["generate"](tmp_path)
    for name in ("autohours.ico", "autohours.icns"):
        assert (tmp_path / name).read_bytes() == (root / "packaging" / name).read_bytes()
