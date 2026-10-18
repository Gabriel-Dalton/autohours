import codecs
import csv
from datetime import timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from autohours.destinations import CSV, Clockify, resolve, sync
from autohours.models import Block, UserError, iso


class StubClockify:
    def __init__(self, entries=None):
        self.entries = entries or []
        self.posts = []
        self.calls = []

    def request(self, method, path, body=None):
        self.calls.append((method, path))
        parsed = urlsplit(path)
        if method == "POST":
            self.posts.append(body)
            self.entries.append({"timeInterval": {"start": body["start"], "end": body["end"]}})
            return {"id": "entry-fake"}
        if parsed.path == "/user":
            return {"id": "user-fake"}
        if parsed.path == "/workspaces":
            return [{"id": "workspace-fake", "name": "My workspace"}]
        if parsed.path.endswith("/projects"):
            return [{"id": "project-acme", "name": "Acme Corp"}, {"id": "project-learning", "name": "Learning"}]
        query = parse_qs(parsed.query)
        assert "start" not in query  # Do not miss a cross-boundary entry.
        page = int(query["page"][0])
        entries = self.entries
        if query.get("in-progress") == ["true"]:
            entries = [e for e in entries if not e["timeInterval"]["end"]]
        return entries[(page - 1) * 100:page * 100]


def test_clockify_overlap_manual_running_and_touching(origin, projects):
    block = Block(origin, origin + timedelta(minutes=20), "Acme Corp", "Project work", True)
    for a, b, expected in [(-10, 1, (0, 1)), (19, 30, (0, 1)), (20, 30, (1, 0)), (-10, 0, (1, 0)), (-100, None, (0, 1))]:
        http = StubClockify([{"timeInterval": {"start": iso(origin + timedelta(minutes=a)), "end": iso(origin + timedelta(minutes=b)) if b is not None else None}}])
        dest = Clockify({"workspace": "My workspace"}, projects, http)
        assert sync(dest, [block], origin, block.end) == expected
        assert http.posts == []


def test_clockify_repeat_and_payload_allowlist(origin, projects):
    http = StubClockify()
    dest = Clockify({"workspace": "workspace-fake"}, projects, http)
    block = Block(origin, origin + timedelta(minutes=20), "Acme Corp", "Project work", True)
    assert sync(dest, [block], origin, block.end, True) == (1, 0)
    assert sync(dest, [block], origin, block.end, True) == (0, 1)
    assert http.posts == [{"start": iso(origin), "end": iso(block.end), "description": "Project work", "billable": True, "projectId": "project-acme"}]


def test_pagination_finds_overlap_after_first_page(origin, projects):
    old = {"timeInterval": {"start": iso(origin - timedelta(days=2)), "end": iso(origin - timedelta(days=1))}}
    http = StubClockify([old] * 100 + [{"timeInterval": {"start": iso(origin), "end": iso(origin + timedelta(hours=1))}}])
    dest = Clockify({"workspace": "My workspace"}, projects, http)
    assert len(dest.existing(origin, origin + timedelta(hours=1))) == 1
    assert any("page=2" in path for _, path in http.calls)


def test_lookup_errors_list_available_and_detect_duplicates():
    items = [{"id": "a", "name": "Acme Corp"}, {"id": "b", "name": "Acme Corp"}]
    with pytest.raises(UserError, match="ambiguous.*Acme Corp"):
        resolve(items, "Acme Corp", "Project")
    with pytest.raises(UserError, match="not found.*Acme Corp"):
        resolve(items, "Missing", "Project")
    assert resolve(items, "a", "Project") == "a"


def test_missing_key(monkeypatch, projects):
    monkeypatch.delenv("CLOCKIFY_API_KEY", raising=False)
    with pytest.raises(UserError, match="CLOCKIFY_API_KEY"):
        Clockify({"workspace": "My workspace"}, projects)


def test_csv_output_quoting_privacy_and_repeat(tmp_path, origin):
    path = tmp_path / "timesheet.csv"
    dest = CSV({"path": str(path)}, timezone.utc)
    block = Block(origin, origin + timedelta(minutes=15), "Acme Corp", 'Work, notes "quoted"', True)
    assert sync(dest, [block], origin, block.end) == (1, 0)
    assert not path.exists()
    assert sync(dest, [block], origin, block.end, True) == (1, 0)
    assert sync(dest, [block], origin, block.end, True) == (0, 1)
    assert path.read_bytes().startswith(codecs.BOM_UTF8)
    with path.open(newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert rows[0] == {"date": "2026-10-16", "start": origin.isoformat(), "end": block.end.isoformat(), "minutes": "15.00", "project": "Acme Corp", "description": block.description, "billable": "true"}


def test_csv_keeps_formula_like_names_as_text(tmp_path, origin):
    path = tmp_path / "timesheet.csv"
    dest = CSV({"path": str(path)}, timezone.utc)
    block = Block(origin, origin + timedelta(minutes=15), "=Acme", "+1 support", True)
    sync(dest, [block], origin, block.end, True)
    with path.open(newline="", encoding="utf-8-sig") as stream:
        row = next(csv.DictReader(stream))
    assert (row["project"], row["description"]) == ("'=Acme", "'+1 support")
    assert [b.project for b in dest.logged(origin, block.end)] == ["=Acme"]


def test_csv_malformed_file_is_preserved(tmp_path, origin):
    path = tmp_path / "timesheet.csv"
    path.write_text("wrong,columns\n")
    with pytest.raises(UserError, match="invalid columns"):
        CSV({"path": str(path)}, timezone.utc).existing(origin, origin + timedelta(hours=1))
    assert path.read_text() == "wrong,columns\n"
