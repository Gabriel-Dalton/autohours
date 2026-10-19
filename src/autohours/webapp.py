"""Private loopback web window. All setup and billing decisions stay in Python."""

from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback
from urllib.parse import parse_qs, quote, unquote, urlsplit
import webbrowser
from zoneinfo import ZoneInfo, available_timezones

from . import desktop, runlog, schedule, setup, taskbar
from .config import config_path, user_config_dir
from .credentials import read_key
from .models import UserError
from .destinations import CSV, OPEN_ELSEWHERE
from .plugins import DESTINATIONS
from .review import span


CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; "
       "script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/index.html": ("index.html", "text/html; charset=utf-8"),
          "/app.css": ("app.css", "text/css; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/icons.svg": ("icons.svg", "image/svg+xml"),
          "/favicon.svg": ("favicon.svg", "image/svg+xml"),
          "/favicon-256.png": ("favicon-256.png", "image/png"),
          "/fonts/IBMPlexSans-Regular.woff2": ("fonts/IBMPlexSans-Regular.woff2", "font/woff2"),
          "/fonts/IBMPlexSans-SemiBold.woff2": ("fonts/IBMPlexSans-SemiBold.woff2", "font/woff2")}


class InputError(UserError):
    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


def valid_day(value):
    try:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        return str(date.fromisoformat(value))
    except ValueError:
        raise InputError("Choose a date, or use Yesterday or Today.", "day") from None


def text_field(data, field, message):
    value = data.get(field)
    if not isinstance(value, str) or not value.strip() or any(not c.isprintable() for c in value):
        raise InputError(message, field)
    return value.strip()


def screen_size():
    """The main screen in scaled pixels on Windows, or None where it is not cheaply known."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        user32 = ctypes.windll.user32
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    except (AttributeError, OSError):
        return None


def window_size(screen):
    """Open larger on larger screens, but never bigger than the screen itself."""
    if not screen or min(screen) <= 0:
        return 1100, 780
    width, height = screen
    return (min(max(round(width * .7), 1100), 1600, width - 80),
            min(max(round(height * .8), 780), 1100, height - 80))


def browser_command(url, platform=None, environment=None, directory=None):
    """Discover a browser without starting it; useful for offline launch tests."""
    platform = platform or sys.platform
    environment = os.environ if environment is None else environment
    directory = directory or user_config_dir() / "window"
    candidates = []
    if platform == "win32":
        for product, executable in (("Microsoft/Edge", "msedge.exe"), ("Google/Chrome", "chrome.exe")):
            for variable in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
                if environment.get(variable):
                    candidates.append(Path(environment[variable]) / product / "Application" / executable)
    elif platform == "darwin":
        candidates = [Path("/Applications") / app / "Contents/MacOS" / binary for app, binary in (
            ("Google Chrome.app", "Google Chrome"), ("Microsoft Edge.app", "Microsoft Edge"),
            ("Brave Browser.app", "Brave Browser"))]
    else:
        candidates = [Path(path) for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge", "brave-browser")
                      if (path := shutil.which(name))]
    browser = next((path for path in candidates if path.is_file()), None)
    if browser:
        return [str(browser), "--app=" + url, "--user-data-dir=" + str(directory),
                "--window-size=%d,%d" % window_size(screen_size() if platform == sys.platform else None),
                "--no-first-run", "--no-default-browser-check"]
    return ["open", url] if platform == "darwin" else None


def open_window(url):
    command = browser_command(url)
    if command:
        try:
            subprocess.Popen(command, **schedule.hidden_console())
            return
        except OSError:
            pass
    webbrowser.open(url)


class Application:
    def __init__(self, session):
        self.session = session
        self.lock = threading.Lock()
        self.readers = 0
        self.timezones = sorted(available_timezones())
        self.status_lock = threading.Lock()
        self.schedule_status = None
        self.schedule_checked = float("-inf")
        self.previews = {}
        self.plan = None
        self.rate_preview = None
        self.secrets = set()
        self.currency = ""
        self.workspace_name = ""
        self.connected_name = ""
        self.project_ids = [secrets.token_urlsafe(12) for _ in session.raw["projects"]]
        if session.original is None:
            session.raw["timezone"] = setup.detected_timezone() or "UTC"
            session.raw["destination"] = {"type": "csv", "path": str(Path.home() / "Documents/autohours-timesheet.csv")}
        try:
            key = read_key()
            if key:
                self.secrets.add(key)
        except (OSError, UserError):
            key = ""
        self.saved_key = bool(key)

    def clean(self, value):
        # Project names and upstream error strings are untrusted too. Redact even
        # if a service accidentally echoes a credential in an otherwise safe field.
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "[private]")
            return value
        if isinstance(value, list):
            return [self.clean(v) for v in value]
        if isinstance(value, dict):
            return {self.clean(k): self.clean(v) for k, v in value.items()}
        return value

    def invalidate(self):
        self.previews.clear()
        self.plan = self.rate_preview = None
        self.session.invalidate_activity()
        self.schedule_checked = float("-inf")

    def projects(self):
        rows = []
        s = self.session
        for index, row in enumerate(s.raw["projects"]):
            assigned = [i for i, ((kind, raw), _) in enumerate(s.items)
                        if setup.item_rule(kind, raw) in row.get(kind, [])]
            values = {**s.raw.get("policy", {}), **row.get("agreement", {})}
            values.setdefault("round_to_minutes", s.raw.get("blocks", {}).get("round_to_minutes", 0))
            # Never export regexes or arbitrary config fields to the view.
            values = {k: v for k, v in values.items() if k not in ("call_apps", "call_titles")}
            target = row.get("destination_project", row["name"])
            target = next((p["id"] for p in s.remote if target in (p["id"], p["name"])), target)
            rows.append({"id": self.project_ids[index], "name": row["name"], "description": row["description"],
                         "items": assigned, "agreement": values,
                         "target": "" if row["name"] in s.pending else target,
                         "create": row["name"] in s.pending})
        return rows

    def state(self):
        s = self.session
        today = datetime.now(ZoneInfo(s.raw["timezone"])).date()
        try:
            with self.status_lock:
                if time.monotonic() - self.schedule_checked >= 30:
                    self.schedule_status = desktop.nightly_status()
                    self.schedule_checked = time.monotonic()
                nightly = self.schedule_status
        except (OSError, UserError):
            nightly = "Status unavailable"
        try:
            last_run = runlog.last_summary(config=s.path, nightly_only=True)
        except OSError:
            last_run = "The recent run log could not be read."
        return {"saved": s.original is not None, "timezone": s.raw["timezone"],
                "timezones": self.timezones, "destination": s.raw["destination"],
                "activitywatch": {k: v for k, v in s.raw["activitywatch"].items() if k != "url"},
                "projects": self.projects(), "saved_key": self.saved_key,
                "schedule": nightly, "last_run": last_run,
                "today": str(today), "yesterday": str(today - timedelta(days=1)),
                "currency": self.currency, "workspace_name": self.workspace_name,
                "clockify_connected": s.http is not None, "single_workspace": len(s.spaces) == 1}

    def choose_workspace(self, identifier):
        s = self.session
        index = next((i for i, row in enumerate(s.spaces) if row["id"] == identifier), None)
        if index is None:
            raise InputError("Choose a workspace.", "workspace")
        s.choose_workspace(index)
        workspace = s.http.request("GET", "/workspaces/" + quote(identifier, safe=""))
        self.currency = (workspace.get("hourlyRate") or {}).get("currency", "")
        self.workspace_name = s.spaces[index]["name"]

    def activity(self):
        s = self.session
        if s.raw["destination"]["type"] == "clockify" and not s.http:
            s.load_projects()
            self.choose_workspace(s.raw["destination"]["workspace"])
        if s.activity is None:
            try:
                s.activity, s.items = s.read_activity(dict(s.raw["activitywatch"]))
            except UserError:
                raise InputError("No recent activity is available yet. Open ActivityWatch, let it record some work, then try again.") from None
        items = []
        covered = self.covered()
        for i, ((kind, raw), minutes) in enumerate(s.items):
            label = desktop.activity_label(kind, raw).rsplit("  ", 2)[0]
            matches = [p["name"] for p in s.raw["projects"] if any(re.search(rule, raw, re.I) for rule in p.get(kind, []))]
            items.append({"id": i, "name": label, "kind": {"app": "App", "title": "Window title", "url": "Website"}[kind],
                          "hours": minutes / 60, "matches": matches, "covered": i in covered})
        return {"items": items, "projects": self.projects(), "coverage": s.coverage(),
                "remote": [{"id": p["id"], "name": p["name"]} for p in s.remote],
                "currency": self.currency, "workspace_name": self.workspace_name}

    def covered(self):
        """Items any project already counts, including window titles inside an app a project has picked."""
        s = self.session
        title_apps = defaultdict(set)
        for event in (s.activity.windows if s.activity else []):
            title_apps[str(event.data.get("title", ""))].add(str(event.data.get("app", "")))
        def hit(kind, value):
            return any(re.search(rule, value, re.I) for p in s.raw["projects"] for rule in p.get(kind, []))
        found = set()
        for i, ((kind, raw), _) in enumerate(s.items):
            if hit(kind, raw) or (kind == "title" and any(hit("app", app) for app in title_apps.get(raw, ()))):
                found.add(i)
        return found

    def set_projects(self, data):
        s = self.session
        rows = data.get("projects")
        if not isinstance(rows, list) or (not rows and data.get("validate", True)):
            raise InputError("Add at least one client or project.", "project-name")
        previous, pending = deepcopy(s.raw["projects"]), s.pending[:]
        previous_ids = self.project_ids[:]
        try:
            s.raw["projects"], s.pending = [], []
            self.project_ids = []
            seen = set()
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    raise InputError("Check this project's details.", "project-name")
                name = text_field(row, "name", "Give this project a name.")
                description = text_field(row, "description", "Add a timesheet description.")
                old_id = row.get("id")
                if old_id is not None and (not isinstance(old_id, str) or old_id not in previous_ids):
                    raise InputError("Your project list changed. Open Projects and billing again.")
                old = previous[previous_ids.index(old_id)] if old_id is not None else {}
                if old_id is not None and old_id in seen:
                    raise InputError("Each project can appear only once.", "project-name")
                seen.add(old_id) if old_id is not None else None
                s.add_project(name, description, row.get("target"), row.get("create") is True)
                self.project_ids.append(old_id or secrets.token_urlsafe(12))
                added = s.raw["projects"][-1]
                # Preserve existing patterns not represented by a picked item.
                for kind in ("app", "url", "title"):
                    known = {setup.item_rule(k, raw) for (k, raw), _ in s.items if k == kind}
                    kept = [r for r in old.get(kind, []) if r not in known]
                    if kept:
                        added[kind] = kept
                added["agreement"] = deepcopy(old.get("agreement", {}))
                if "billable" in old:
                    added["billable"] = old["billable"]
                choices = row.get("items", [])
                if not isinstance(choices, list) or any(type(i) is not int or not 0 <= i < len(s.items) for i in choices):
                    raise InputError("Refresh your activity and pick it again.", "activity")
                for item in choices:
                    # The Session owns escaping and the one-item assignment rule.
                    s.assign(index, item, True)
            for index, row in enumerate(s.raw["projects"]):
                if not any(row.get(k) for k in ("app", "url", "title")) and data.get("validate", True):
                    raise InputError(f"Pick at least one activity for {row['name']}.", f"project-{index}")
        except Exception:
            s.raw["projects"], s.pending = previous, pending
            self.project_ids = previous_ids
            raise
        self.invalidate()
        return {"projects": self.projects(), "coverage": s.coverage(), "covered": sorted(self.covered())}

    def agreements(self, data):
        s = self.session
        rows = data.get("agreements")
        if not isinstance(rows, list) or len(rows) != len(s.raw["projects"]):
            raise InputError("Choose how you bill each project.", "billing-0")
        result = []
        for i, values in enumerate(rows):
            if not isinstance(values, dict) or values.get("billing") not in ("hourly", "flat", "retainer", "none"):
                raise InputError("Choose how you bill this client.", f"billing-{i}")
            fields = {"rate": "", "currency": "", "monthly_cap_hours": "", "count_breaks_up_to_minutes": 0,
                      "round_to_minutes": 0, "rounding": "nearest", "count_calls_when_away": False, **values}
            for field in ("rate", "monthly_cap_hours", "count_breaks_up_to_minutes", "round_to_minutes"):
                try:
                    setup.number(str(fields[field]), whole=field.endswith("minutes"), optional=field in ("rate", "monthly_cap_hours"))
                except ValueError:
                    message = "Enter a whole number from 0 to 1440." if field.endswith("minutes") else "Enter a positive number or zero. You can leave this empty."
                    raise InputError(message, f"{field}-{i}") from None
            if not isinstance(fields["currency"], str) or (fields["currency"] and not re.fullmatch(r"[A-Za-z]{3}", fields["currency"].strip())):
                raise InputError("Use a three-letter currency, such as CAD, or leave it empty.", f"currency-{i}")
            result.append(desktop.agreement(fields, s.raw["projects"][i].get("agreement")))
        for row, value in zip(s.raw["projects"], result):
            row["agreement"] = value
        self.invalidate()
        return {"ok": True}

    def review(self, day):
        cfg, result = self.session.review(valid_day(day))
        amounts = defaultdict(Decimal)
        for i, project in enumerate(cfg.projects):
            values = project.agreement or {}
            if values.get("billing") == "hourly" and "rate" in values and "currency" in values:
                amounts[values["currency"]] += Decimal(str(sum(r.billed for r in result.reviews if r.project == i))) * Decimal(str(values["rate"])) / 60
        names = {p.destination_project: p.name for p in cfg.projects}
        short_pieces = [sum(s.minutes for s in row.segments if s.kind in ("worked", "call", "accepted", "counted-break"))
                        for row in result.reviews if row.filtered]
        return {"day": day, "hours": sum(b.minutes for b in result.blocks) / 60,
                "minutes": sum(b.minutes for b in result.blocks),
                "amounts": [f"{value:.2f} {currency}" for currency, value in sorted(amounts.items())],
                "entries": [{"time": span(b.start, b.end, cfg.timezone), "hours": b.minutes / 60, "minutes": b.minutes,
                             "project": names.get(b.project, b.project), "description": b.description} for b in result.blocks],
                "unmatched": sum(result.unmatched.values()), "short": result.discarded_minutes,
                "unmatched_minutes": sum(result.unmatched.values()),
                "short_piece_minutes": sum(minutes for minutes in short_pieces if minutes < cfg.blocks["min_block_minutes"]),
                "minimum_minutes": cfg.blocks["min_block_minutes"]}

    def dispatch(self, method, path, data, query):
        s = self.session
        route = (method, path)
        if route == ("GET", "/api/state"):
            return self.state()
        if route == ("POST", "/api/reset"):
            self.session = desktop.Session(s.path)
            self.project_ids = [secrets.token_urlsafe(12) for _ in self.session.raw["projects"]]
            self.invalidate()
            return {"ok": True}
        if route == ("POST", "/api/timezone"):
            zone = text_field(data, "timezone", "Choose your time zone.")
            if zone not in available_timezones():
                raise InputError("Choose a time zone from the list.", "timezone")
            s.raw["timezone"] = zone
            self.invalidate()
            return {"ok": True}
        if route == ("POST", "/api/activitywatch/check"):
            try:
                hosts = s.hosts()
            except UserError:
                return {"running": False, "hosts": [], "message": "Open ActivityWatch to start recording your apps and time away."}
            host = data.get("hostname", s.raw["activitywatch"].get("hostname"))
            host = hosts[0] if len(hosts) == 1 else host
            if host not in hosts:
                return {"running": False, "hosts": hosts, "message": "Choose the computer you use for work."}
            settings = s.raw["activitywatch"]
            settings["hostname"] = host
            if "use_web" in data:
                if type(data["use_web"]) is not bool:
                    raise InputError("Choose whether to include websites.", "use_web")
                if data["use_web"]:
                    settings["use_web"] = True
                else:
                    settings.pop("use_web", None)
            s.activity, s.items = None, []
            try:
                s.check_buckets()
            except UserError as exc:
                message = ("ActivityWatch is open, but no websites have arrived from its browser extension. "
                           "Install the ActivityWatch extension in your browser, or turn off website matching."
                           if str(exc).startswith("No web watcher") else
                           "ActivityWatch is open. Enable app and away-time recording in its settings.")
                return {"running": False, "hosts": hosts, "hostname": host, "message": message}
            self.invalidate()
            return {"running": True, "hosts": hosts, "hostname": host, "message": "ActivityWatch is running on this computer."}
        if route == ("POST", "/api/destination"):
            kind = data.get("type")
            if kind not in ("csv", "clockify"):
                raise InputError("Choose where your timesheets should go.", "destination")
            if kind != s.raw["destination"]["type"] and s.raw["projects"]:
                raise InputError("Remove your current projects before changing the destination, then add them for the new destination.", "destination")
            if kind == "csv":
                path_value = text_field(data, "path", "Choose a filename for your spreadsheet.")
                target = Path(path_value).expanduser().resolve()
                if target.is_dir() or not target.parent.is_dir():
                    raise InputError("Choose a filename inside an existing folder.", "path")
                if target.is_file() and target.stat().st_size:
                    try:
                        CSV({"path": str(target)}, ZoneInfo("UTC")).existing(datetime.min.replace(tzinfo=ZoneInfo("UTC")), datetime.max.replace(tzinfo=ZoneInfo("UTC")))
                    except UserError as exc:
                        if str(exc) == OPEN_ELSEWHERE:
                            raise InputError(OPEN_ELSEWHERE, "path") from None
                        raise InputError("This file already holds other data. Choose a new filename, or an autohours timesheet you used before.", "path") from None
                s.raw["destination"] = {"type": kind, "path": str(target)}
                s.key, s.http, s.pending = None, None, []
                self.currency = self.workspace_name = ""
            elif s.raw["destination"]["type"] != kind:
                s.raw["destination"] = {"type": kind}
            self.invalidate()
            return {"ok": True}
        if route == ("POST", "/api/clockify/key"):
            candidate = data.get("key", "")
            if not isinstance(candidate, str):
                raise InputError("Paste your Clockify API key.", "key")
            if candidate.strip():
                self.secrets.add(candidate.strip())
            s.key = s.http = None
            try:
                s.check_key(candidate)
                if s.key:
                    self.secrets.add(s.key)
                user = s.http.request("GET", "/user")
            except UserError:
                raise InputError("We could not connect. Check the key and your internet connection, then try again.", "key") from None
            self.connected_name = user.get("name") or "your Clockify account"
            if len(s.spaces) == 1:
                self.choose_workspace(s.spaces[0]["id"])
            return {"name": self.connected_name, "single_workspace": len(s.spaces) == 1,
                    "workspace_name": self.workspace_name, "currency": self.currency}
        if route == ("GET", "/api/clockify/workspaces"):
            return {"workspaces": [{"id": row["id"], "name": row["name"]} for row in s.spaces]}
        if route == ("POST", "/api/clockify/workspace"):
            self.choose_workspace(data.get("workspace"))
            self.invalidate()
            return {"currency": self.currency, "workspace_name": self.workspace_name}
        if route == ("GET", "/api/activity"):
            return self.activity()
        if route == ("POST", "/api/projects"):
            return self.set_projects(data)
        if route == ("GET", "/api/coverage"):
            return {"coverage": s.coverage()}
        if route == ("POST", "/api/agreements"):
            return self.agreements(data)
        if route == ("POST", "/api/save"):
            if not s.raw["projects"]:
                raise InputError("Add at least one client or project.", "project-name")
            for i, row in enumerate(s.raw["projects"]):
                if not any(row.get(k) for k in ("app", "url", "title")):
                    raise InputError(f"Pick at least one activity for {row['name']}.", f"project-{i}")
                if not row.get("agreement", {}).get("billing"):
                    raise InputError("Choose how you bill this client.", f"billing-{i}")
            s.save()
            if s.raw["destination"]["type"] == "clockify" and s.http:
                s.remote = setup.remote_projects(s.http, s.raw["destination"]["workspace"])
            self.saved_key = self.saved_key or bool(self.secrets)
            self.invalidate()
            return {"saved": True}
        if route == ("GET", "/api/doctor"):
            s.require_saved()
            cfg = s.config()
            checks = [{"ok": True, "message": "Your settings are saved and ready."}]
            for factory, label, fix in ((s.activity_source, "ActivityWatch is recording your apps and time away.", "Open ActivityWatch and enable app and away-time recording."),
                                       (lambda: DESTINATIONS[cfg.destination["type"]](cfg), "Your timesheet destination is ready.", "Check your destination settings, file permissions or Clockify connection.")):
                try:
                    factory().check()
                    checks.append({"ok": True, "message": label})
                except (UserError, OSError):
                    checks.append({"ok": False, "message": fix})
            return {"checks": checks}
        if route == ("GET", "/api/rates"):
            messages, failed = s.rates()
            self.rate_preview = (secrets.token_urlsafe(16), messages)
            return {"messages": plain_rates(messages), "changes": any(" -> " in m for m in messages),
                    "failed": failed, "preview": self.rate_preview[0]}
        if route == ("POST", "/api/rates/apply"):
            self.confirm(data, self.rate_preview[0] if self.rate_preview else None)
            if s.rates()[0] != self.rate_preview[1]:
                self.rate_preview = None
                raise InputError("Clockify settings changed. Check the rate differences again before updating.")
            self.rate_preview = None
            messages, failed = s.rates(True)
            return {"messages": plain_rates([m for m in messages if " -> " not in m]), "failed": failed}
        if route == ("GET", "/api/review"):
            return self.review(query.get("day", [""])[0])
        if route == ("POST", "/api/write/preview"):
            day = valid_day(data.get("day"))
            review = self.review(day)
            preview = s.command("sync", day)
            totals = re.search(r"Ready to write: (\d+) entries, ([\d.]+) h\.", preview)
            identifier = secrets.token_urlsafe(16)
            self.previews[day] = identifier
            return {**review, "count": int(totals[1]) if totals else len(review["entries"]),
                    "hours": float(totals[2]) if totals else review["hours"],
                    "text": preview, "preview": identifier, "destination": s.raw["destination"]}
        if route == ("POST", "/api/write"):
            day = valid_day(data.get("day"))
            self.confirm(data, self.previews.get(day))
            self.previews.pop(day, None)  # Partial failures require a fresh preview.
            started = ("Run started: " + datetime.now().isoformat(timespec="seconds")
                       + "\nRun config: " + runlog.config_id(s.path) + "\nRun kind: manual\nWrite phase started.")
            try:
                result = s.command("sync", day, "--write")
            except (UserError, OSError) as exc:
                log_event(started + "\nRun finished: needs attention")
                reason = f"{exc} " if str(exc) == OPEN_ELSEWHERE else ""
                raise InputError(reason + "The write did not finish. Some entries may already be saved. Review this day again before retrying.") from None
            log_event(started + "\n" + self.clean(result) + "\nRun finished: success")
            summary = re.search(r"Wrote (\d+) entries, ([\d.]+) h\.", result)
            skipped = re.search(r"Created \d+, skipped (\d+)", result)
            message = "Your timesheet was written."
            if summary:
                count, minutes = int(summary[1]), round(float(summary[2]) * 60)
                length = f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"
                message = f"Wrote {count} {'entry' if count == 1 else 'entries'} ({length})."
            if skipped and int(skipped[1]):
                message += f" Skipped {skipped[1]} already logged."
            return {"message": message}
        if route == ("POST", "/api/review/open"):
            cfg, result = s.review(valid_day(data.get("day")))
            path_value = desktop.full_report(cfg, result)
            webbrowser.open(path_value.as_uri())
            return {"ok": True}
        if route == ("GET", "/api/schedule/plan"):
            s.require_saved()
            s.doctor()
            try:
                at = schedule.clock(query.get("at", ["06:00"])[0])
            except ValueError:
                raise InputError("Choose a time from 00:00 to 23:59.", "at") from None
            cron = schedule.read_crontab() if sys.platform not in ("win32", "darwin") else ""
            plan = schedule.build_plan(s.path, at, crontab=cron)
            identifier = secrets.token_urlsafe(16)
            self.plan = (identifier, plan)
            return {"preview": identifier, "at": at, "text": plan.describe()}
        if route == ("POST", "/api/schedule"):
            self.confirm(data, self.plan[0] if self.plan else None)
            s.require_saved()
            plan = self.plan[1]
            self.plan = None
            schedule.install(plan)
            self.schedule_checked = float("-inf")
            return {"message": "Every morning is now on."}
        if route == ("DELETE", "/api/schedule"):
            if data.get("confirm") is not True:
                raise InputError("Confirm that you want to stop automatic writes.", "confirm")
            schedule.remove()
            self.schedule_checked = float("-inf")
            return {"message": "Every morning is now off."}
        if route == ("POST", "/api/settings/open"):
            desktop.open_settings(s.path)
            return {"ok": True}
        raise InputError("This action is not available. Reopen the app and try again.")

    @staticmethod
    def confirm(data, preview):
        if data.get("confirm") is not True or not preview or data.get("preview") != preview:
            raise InputError("Review the preview and confirm this action first.", "confirm")


def log_event(message):
    """Append privately without changing process-wide stdout in request threads."""
    try:
        directory = runlog.log_directory()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        runlog.prune(directory, date.today())
        path = directory / f"{date.today()}.log"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        path.chmod(0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
            stream.write(message + "\n")
    except OSError:
        pass  # An unavailable log must not expose an exception to the page.


class Server(ThreadingHTTPServer):
    daemon_threads = False

    def __init__(self, session, first_timeout=60, heartbeat_timeout=20):
        self.app = Application(session)
        self.token = secrets.token_urlsafe(32)
        self.bootstrap = secrets.token_urlsafe(32)
        self.bootstrap_lock = threading.Lock()
        self.first_timeout, self.heartbeat_timeout = first_timeout, heartbeat_timeout
        self.started = time.monotonic()
        self.heartbeat = None
        self.stopping = threading.Event()
        super().__init__(("127.0.0.1", 0), Handler)
        self.host = f"127.0.0.1:{self.server_port}"
        self.origin = "http://" + self.host
        self.url = self.origin + "/#b=" + self.bootstrap

    def clean_error(self, message):
        for secret in (self.token, self.url.split("#b=", 1)[1]):
            message = message.replace(secret, "[private]")
        return self.app.clean(message)

    def handle_error(self, request, client_address):
        error = sys.exc_info()[1]
        if isinstance(error, ConnectionError) or (
            isinstance(error, OSError) and getattr(error, "winerror", None) in (10053, 10054)
        ):
            return
        log_event(self.clean_error(traceback.format_exc()))

    def redeem_bootstrap(self, code):
        with self.bootstrap_lock:
            if (not isinstance(code, str) or self.bootstrap is None
                    or time.monotonic() - self.started >= 120
                    or not hmac.compare_digest(code.encode("utf-8", errors="surrogatepass"), self.bootstrap.encode("ascii"))):
                return False
            self.bootstrap = None
            return True

    def serve_forever(self, poll_interval=0.1):
        monitor = threading.Thread(target=self.watch_lifetime, daemon=True)
        monitor.start()
        try:
            super().serve_forever(poll_interval)
        finally:
            self.stopping.set()
            monitor.join(timeout=1)

    def watch_lifetime(self):
        while not self.stopping.wait(0.05):
            last = self.heartbeat
            if time.monotonic() - (last if last is not None else self.started) > (self.heartbeat_timeout if last is not None else self.first_timeout):
                self.shutdown()
                return


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        pass  # No URLs, request bodies, credentials or activity in access logs.

    def send_error(self, code, message=None, explain=None):
        self.respond(code, {"error": "This request could not be accepted."})

    def respond(self, status, value, content_type="application/json; charset=utf-8"):
        try:
            self.write_response(status, value, content_type)
        except ConnectionError:
            self.close_connection = True
        except OSError as exc:
            if getattr(exc, "winerror", None) not in (10053, 10054):
                raise
            self.close_connection = True

    def write_response(self, status, value, content_type):
        body = value if isinstance(value, bytes) else json.dumps(self.server.app.clean(value), ensure_ascii=True).encode("utf-8")
        self.response_started = True
        self.send_response(status)
        for key, text in (("Content-Type", content_type), ("Content-Length", str(len(body))),
                          ("Content-Security-Policy", CSP), ("X-Content-Type-Options", "nosniff"),
                          ("Cache-Control", "no-store"), ("Referrer-Policy", "no-referrer")):
            self.send_header(key, text)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def handle_request(self):
        self.response_started = False
        server = self.server
        if self.headers.get_all("Host") != [server.host] or (self.headers.get_all("Origin") is not None and self.headers.get_all("Origin") != [server.origin]):
            self.respond(403, {"error": "Open this app using its local window address."})
            return
        parsed = urlsplit(self.path)
        path = unquote(parsed.path)
        if parsed.scheme or parsed.netloc or "%" in path or "\\" in path or any(p in (".", "..") for p in path.split("/")):
            self.respond(400, {"error": "This address is not available."})
            return
        if not path.startswith("/api/"):
            if self.command not in ("GET", "HEAD") or path not in STATIC:
                self.respond(404, {"error": "This page is not available."})
                return
            filename, mime = STATIC[path]
            self.respond(200, (Path(__file__).parent / "web" / filename).read_bytes(), mime)
            return
        if self.command == "POST" and path == "/api/session":
            try:
                valid = server.redeem_bootstrap(self.read_data().get("bootstrap"))
            except InputError:
                valid = False
            if valid:
                self.respond(200, {"token": server.token})
            else:
                self.respond(403, {"error": "This window has expired. Close it and open autohours again."})
            return
        tokens = self.headers.get_all("X-Autohours-Token", [])
        if len(tokens) != 1 or not hmac.compare_digest(tokens[0].encode("utf-8"), server.token.encode("ascii")):
            self.respond(403, {"error": "Reopen autohours to connect this window."})
            return
        if self.command == "POST" and path in ("/api/heartbeat", "/api/quit"):
            server.heartbeat = time.monotonic()
            self.respond(200, {"ok": True})
            if path.endswith("/quit"):
                threading.Thread(target=server.shutdown, daemon=True).start()
            return
        if not server.app.lock.acquire(blocking=False):
            self.respond(409, {"error": "Another check or save is still running. Try this action again in a moment."})
            return
        # Only these pure reads may overlap. Mutations (including previews) keep
        # exclusive access, and cannot change configuration under an active read.
        shared = self.command == "GET" and path in ("/api/state", "/api/doctor", "/api/review")
        if not shared and server.app.readers:
            server.app.lock.release()
            self.respond(409, {"error": "Another check is still running. Try this action again in a moment."})
            return
        if shared:
            server.app.readers += 1
            server.app.lock.release()
        try:
            data = {}
            if self.command in ("POST", "DELETE"):
                data = self.read_data()
            result = server.app.dispatch(self.command, path, data, parse_qs(parsed.query))
            self.respond(200, result)
        except InputError as exc:
            self.respond(400, {"error": str(exc), **({"field": exc.field} if exc.field else {})})
        except (UserError, ValueError) as exc:
            self.respond(400, {"error": str(exc)})
        except ConnectionError:
            pass
        except Exception:
            log_event(server.clean_error(traceback.format_exc()))
            if not self.response_started:
                self.respond(500, {"error": "Something went wrong. Try again, or close and reopen autohours. Details are in your private run log."})
        finally:
            if shared:
                with server.app.lock:
                    server.app.readers -= 1
            else:
                server.app.lock.release()

    def read_data(self):
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not lengths[0].isdigit() or int(lengths[0]) > 1024 * 1024 or self.headers.get("Transfer-Encoding"):
            raise InputError("This request is too large or incomplete.")
        if self.headers.get_content_type() != "application/json":
            raise InputError("Send this action from the autohours window.")
        try:
            data = json.loads(self.rfile.read(int(lengths[0])))
        except (ValueError, UnicodeError):
            raise InputError("This request is incomplete. Try again.") from None
        if not isinstance(data, dict):
            raise InputError("This request is incomplete. Try again.")
        return data

    do_GET = do_POST = do_DELETE = do_HEAD = do_OPTIONS = handle_request


def plain_rates(lines):
    """One line per project where possible: an 'in sync' line adds nothing when the project already has a note."""
    noted = {line.partition(": ")[0] for line in lines if " in sync" not in line}
    return [plain_rate(line) for line in lines if not (": in sync" in line and line.partition(": ")[0] in noted)]


def plain_rate(line):
    """The rate check's command line wording, in the plain English the app uses."""
    name, _, detail = line.partition(": ")
    detail = detail.replace("/h", " per hour")
    if " -> " in detail:
        before, after = detail.rsplit(" -> ", 1)
        if before.startswith("hourly rate "):
            old = before.removeprefix("hourly rate ")
            return f"{name}: hourly rate set to {after}" if old == "not set" else f"{name}: hourly rate changes from {old} to {after}"
        return f"{name}: becomes {after}"
    if detail == "rate not set; rate unchanged.":
        return f"{name}: no hourly rate yet, so Clockify is left as it is."
    if detail == "currency not set; rate unchanged.":
        return f"{name}: no currency yet, so Clockify is left as it is."
    found = re.fullmatch(r"workspace currency (\S+) differs from agreement (\S+); refusing to apply rate\.", detail)
    if found:
        return f"{name}: your Clockify workspace uses {found[1]} but this client is billed in {found[2]}, so the rate is not changed."
    if detail.startswith("in sync"):
        return f"{name}: already matches ({detail.removeprefix('in sync (').rstrip(')')})"
    if detail.startswith("confirmed; "):
        rest = detail.removeprefix("confirmed; ").replace("hourly rate=", "")
        return f"{name}: updated and checked. {rest[:1].upper()}{rest[1:]}"
    if detail.startswith("MISMATCH"):
        return f"{name}: Clockify shows different values after the update. Check this project in Clockify."
    return line


def startup_alert(message):
    """A windowed app has no terminal, so a settings problem at launch is shown in a system dialog."""
    if os.environ.get("AUTOHOURS_NO_WINDOW") or (sys.stderr is not None and not getattr(sys, "frozen", False)):
        return
    title = "autohours could not open"
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
        elif sys.platform == "darwin":
            subprocess.run(["osascript", "-e", f"display alert {json.dumps(title)} message {json.dumps(message)} as critical"], check=False)
    except OSError:
        pass


def launch(explicit=None):
    try:
        server = Server(desktop.Session(explicit))
    except UserError as exc:
        startup_alert(f"{exc}\n\nFix your settings file, or move it somewhere else to set up autohours again:\n{config_path(explicit)}")
        raise
    except OSError:
        raise UserError("Could not open the local app. Check that your computer allows local connections.") from None
    with server:
        if sys.stdout is not None:
            print("Open autohours: " + server.url, flush=True)
        if not os.environ.get("AUTOHOURS_NO_WINDOW"):
            open_window(server.url)
            taskbar.label_in_background()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0
