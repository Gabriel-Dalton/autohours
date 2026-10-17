"""Desktop operations without Tk dependencies or implicit destination writes."""

from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import os
from pathlib import Path
import tempfile
import tomllib
import subprocess
import sys

from . import setup
from .cli import parser, review_period, run
from .config import agreement_table, config_path, load_config, parse_config
from .credentials import read_key
from .models import UserError
from .plugins import DESTINATIONS, SOURCES
from .rates import compare
from .review import html_review


def agreement(values, previous=None):
    result = dict(previous or {})
    for field in ("rate", "monthly_cap_hours", "count_breaks_up_to_minutes", "round_to_minutes"):
        text = str(values[field])
        if field == "round_to_minutes" and text == "none":
            text = "0"
        value = setup.number(text, whole=field.endswith("minutes"),
                             optional=field in ("rate", "monthly_cap_hours"))
        result.pop(field, None)
        if value is not None:
            result[field] = value
    result.update(billing=values["billing"], rounding=values["rounding"],
                  count_calls_when_away=values["count_calls_when_away"])
    result.pop("currency", None)
    if values["currency"].strip():
        result["currency"] = values["currency"].strip().upper()
    return agreement_table(result, "Agreement")


class Session:
    def __init__(self, explicit=None):
        self.path = config_path(explicit).resolve()
        self.original = self.path.read_text(encoding="utf-8") if self.path.exists() else None
        if self.original is not None:
            load_config(self.path)
        self.raw = tomllib.loads(self.original) if self.original else {
            "timezone": "UTC", "activitywatch": {"url": "http://localhost:5600"},
            "destination": {"type": "csv", "path": str(Path.home() / "timesheet.csv")}, "projects": []}
        self.raw.setdefault("activitywatch", {}).setdefault("url", "http://localhost:5600")
        for row in self.raw["projects"]:
            row.setdefault("agreement", {})
        self.key = None
        self.http = None
        self.spaces = []
        self.remote = []
        self.pending = []
        self.items = []
        self.activity = None
        self.now = datetime.now(timezone.utc)

    def config(self):
        return parse_config(deepcopy(self.raw), self.path)

    def hosts(self):
        source = setup.ActivityWatch(self.raw["activitywatch"])
        return setup.activity_hosts(source.http.request("GET", "/buckets/"))

    def check_activity(self):
        source = setup.ActivityWatch(self.raw["activitywatch"])
        message = source.check()
        self.activity = setup.recent_activity(source, self.now)
        self.items = setup.activity_items(self.activity, self.now - timedelta(days=7), self.now)
        if not self.items:
            raise UserError("No active time recorded in the last seven days. Let ActivityWatch record some work and check again.")
        return message

    def check_key(self, candidate=""):
        # No secret is returned to the view or included in an error message.
        key = candidate.strip() or read_key()
        try:
            http = setup.verify_key(key)
            spaces = setup.workspaces(http)
        except (UserError, OSError):
            raise UserError("Could not verify the key. Check your connection and copy the key from Clockify settings.") from None
        self.key, self.http, self.spaces = key, http, spaces
        return [s["name"] for s in spaces]

    def choose_workspace(self, index):
        identifier = self.spaces[index]["id"]
        previous = self.raw["destination"].get("workspace")
        if previous and previous != identifier and self.raw["projects"]:
            raise UserError("Projects already belong to another workspace. Remove them before changing workspace.")
        self.raw["destination"] = {"type": "clockify", "workspace": identifier}
        self.remote = setup.remote_projects(self.http, identifier)

    def load_projects(self):
        if self.raw["destination"]["type"] == "clockify":
            self.check_key()
            identifier = setup.resolve(self.spaces, self.raw["destination"]["workspace"], "Workspace")
            self.remote = setup.remote_projects(self.http, identifier)
        self.check_activity()

    def add_project(self, name, description, target=None, create=False):
        name, description = setup.nonempty(name.strip()), setup.nonempty(description.strip())
        if any(p["name"] == name for p in self.raw["projects"]):
            raise UserError("Choose a name that is not already in your project list.")
        row = {"name": name, "description": description, "agreement": {}}
        if self.raw["destination"]["type"] == "clockify":
            if create:
                if not 2 <= len(name) <= 250:
                    raise UserError("Clockify project names need 2 to 250 characters.")
                if any(p["name"] == name for p in self.remote):
                    raise UserError("That project already exists in Clockify. Select it from the list.")
                self.pending.append(name)
            else:
                selected = next((p for p in self.remote if p["id"] == target), None)
                if selected is None:
                    raise UserError("Select a Clockify project, or choose Create new.")
                if any(p.get("destination_project", p["name"]) in (target, selected["name"])
                       for p in self.raw["projects"]):
                    raise UserError("That Clockify project is already assigned. Select another.")
                row["destination_project"] = target
        self.raw["projects"].append(row)

    def assign(self, project, item, checked):
        kind, text = self.items[item][0]
        rule = setup.item_rule(kind, text)
        # One picked item belongs to one project. Existing unrelated rules remain.
        for i, row in enumerate(self.raw["projects"]):
            if checked or i == project:
                row[kind] = [r for r in row.get(kind, []) if r != rule]
                if not row[kind]:
                    row.pop(kind, None)
        if checked:
            self.raw["projects"][project].setdefault(kind, []).append(rule)

    def coverage(self):
        if self.activity is None or not self.raw["projects"]:
            return 0
        # Projects awaiting their first choice have no rules yet.
        raw = deepcopy(self.raw)
        raw["projects"] = [p for p in raw["projects"] if any(p.get(k) for k in ("app", "url", "title"))]
        if not raw["projects"]:
            return 0
        cfg = parse_config(raw, self.path)
        covered, total = setup.coverage(self.activity, cfg, self.now - timedelta(days=7), self.now)
        return covered / total * 100 if total else 0

    def save(self):
        self.config()
        text = setup.config_text(self.raw)
        if self.original:
            # The editor changes projects only. Preserve the original top-level
            # settings and comments when they have not changed.
            import re
            old = tomllib.loads(self.original)
            if {k: v for k, v in old.items() if k != "projects"} == {k: v for k, v in self.raw.items() if k != "projects"}:
                pieces = re.split(r"(?m)^\s*\[\[projects\]\][^\n]*\n", self.original)
                if (len(pieces) == len(old["projects"]) + 1
                        and tomllib.loads(pieces[0]) == {k: v for k, v in old.items() if k != "projects"}):
                    blocks = {row["name"]: (row, "\n[[projects]]\n" + body)
                              for row, body in zip(old["projects"], pieces[1:])}
                    text = pieces[0]
                    for row in self.raw["projects"]:
                        previous, block = blocks.get(row["name"], (None, ""))
                        text += block if row == previous else setup.project_text(row)
        cfg = setup.save_settings((self.path, self.original, text, self.key, self.http,
                                   self.pending, self.raw), lambda _: None)
        self.original = text
        self.pending = []
        self.key = None
        return cfg

    def review(self, day):
        cfg = self.config()
        return cfg, review_period(cfg, [day])[2]

    def rates(self, apply=False):
        if apply:
            self.require_saved()
        cfg = self.config()
        if cfg.destination["type"] != "clockify":
            return "Spreadsheet selected. Clockify rates do not apply.", False
        return compare(DESTINATIONS["clockify"](cfg), apply)

    def command(self, *args):
        self.require_saved()
        output = io.StringIO()
        with redirect_stdout(output):
            status = run(parser().parse_args(["--config", str(self.path), *args]))
        if status:
            raise UserError(output.getvalue() or "The check needs attention before writing.")
        return output.getvalue()

    def require_saved(self):
        current = self.path.read_text(encoding="utf-8") if self.path.exists() else None
        if current != self.original or current is None:
            raise UserError("Settings changed outside the app. Reopen the app and review again before writing.")
        if setup.config_text(tomllib.loads(current)) != setup.config_text(self.raw):
            raise UserError("Save your changed settings and review again before writing.")

    def doctor(self):
        cfg = self.config()
        return SOURCES["activitywatch"](cfg).check() + "\n" + DESTINATIONS[cfg.destination["type"]](cfg).check()


def full_report(config, result):
    descriptor, name = tempfile.mkstemp(prefix="autohours-review-", suffix=".html")
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(html_review(result, config.projects, config.timezone))
    return Path(name)


def open_settings(path):
    if sys.platform == "win32":
        try:
            os.startfile(str(path))
        except OSError:
            # TOML commonly has no registered editor on a first installation.
            subprocess.Popen(["notepad.exe", str(path)])
    else:
        command = ["open", "-t", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
        subprocess.run(command, check=True, capture_output=True)
