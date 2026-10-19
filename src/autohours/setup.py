"""Conversational setup. Collect answers before committing any changes."""

from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from getpass import getpass
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib
from urllib.parse import quote, urlsplit
import warnings
from getpass import GetPassWarning
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from . import CONFIG_NAME
from .activitywatch import ActivityWatch
from .config import config_path, load_config, parse_config, user_config_dir
from .credentials import atomic_write, read_key, save_key, valid_key
from .destinations import Clockify, resolve
from .http import JsonHTTP
from .models import Project, UserError
from .pipeline import active_slices, build
from .review import safe


class Back(Exception):
    pass


class Quit(Exception):
    pass


class Prompts:
    """Replay earlier answers to go back without retaining partial config mutations."""

    def __init__(self, input_fn=None, secret_fn=None, output=print):
        self.input = input_fn or input
        self.secret = secret_fn or getpass
        self.output = output
        self.answers = []
        self.cursor = 0

    def say(self, message):
        if self.cursor >= len(self.answers):
            self.output("\n".join(safe(line) for line in str(message).splitlines()))

    def ask(self, question, default=None, validate=None, secret=False):
        prompt = question + (f" [{default}]" if default is not None else "") + ": "
        if self.cursor < len(self.answers):
            previous_prompt, value = self.answers[self.cursor]
            if previous_prompt == prompt:
                self.cursor += 1
                return value
            # A recovered service may skip an earlier retry question.
            del self.answers[self.cursor:]
        while True:
            # Never let getpass fall back to echoed input in a redirected terminal.
            with warnings.catch_warnings():
                warnings.simplefilter("error", GetPassWarning)
                try:
                    value = (self.secret if secret else self.input)(prompt).strip()
                except GetPassWarning:
                    raise UserError("Hidden input is unavailable. Run autohours setup in an interactive terminal.") from None
            if value.lower() in ("quit", "q"):
                raise Quit
            if value.lower() in ("back", "b"):
                if not self.answers:
                    self.say("You are at the first question. Type quit to stop.")
                    continue
                self.answers.pop()
                raise Back
            value = value or (str(default) if default is not None else "")
            try:
                result = validate(value) if validate else value
            except (ValueError, UserError) as exc:
                self.say(str(exc) or "Please enter a valid answer.")
                continue
            self.answers.append((prompt, result))
            self.cursor += 1
            return result

    def choose(self, question, labels, default=1):
        for i, label in enumerate(labels, 1):
            self.say(f"  {i}. {label}")
        def number(value):
            if not value.isdigit() or not 1 <= int(value) <= len(labels):
                raise ValueError("Choose a number from the list.")
            return int(value) - 1
        return self.ask(question, default, number)

    def yes(self, question, default=False):
        def boolean(value):
            if value.lower() not in ("yes", "y", "no", "n"):
                raise ValueError("Please answer yes or no.")
            return value.lower() in ("yes", "y")
        return self.ask(question, "yes" if default else "no", boolean)

    def checkpoint(self):
        # Back never crosses a completed write or an explicit decision to leave a stage.
        self.answers.clear()
        self.cursor = 0

    def collect(self, callback):
        while True:
            self.cursor = 0
            try:
                return callback()
            except Back:
                continue


def nonempty(value):
    if not value or any(not c.isprintable() for c in value):
        raise ValueError("Enter some text, or type back or quit.")
    return value


def number(value, whole=False, optional=False):
    if optional and not value:
        return None
    try:
        result = int(value) if whole else float(value)
    except ValueError:
        raise ValueError("Enter a non-negative number." + (" Leave blank to skip." if optional else "")) from None
    if not math.isfinite(result) or result < 0 or (whole and result > 1440):
        raise ValueError("Enter a non-negative number" + (" from 0 to 1440." if whole else "."))
    return result


def detected_timezone():
    candidates = [os.environ.get("TZ", "").lstrip(":")]
    if sys.platform == "win32":
        # Windows stores Windows zone names rather than IANA identifiers.
        zones = {"UTC": "UTC", "Pacific Standard Time": "America/Los_Angeles",
                 "Mountain Standard Time": "America/Denver", "US Mountain Standard Time": "America/Phoenix",
                 "Central Standard Time": "America/Chicago", "Eastern Standard Time": "America/New_York",
                 "Atlantic Standard Time": "America/Halifax", "Newfoundland Standard Time": "America/St_Johns",
                 "Alaskan Standard Time": "America/Anchorage", "Hawaiian Standard Time": "Pacific/Honolulu",
                 "GMT Standard Time": "Europe/London", "W. Europe Standard Time": "Europe/Berlin",
                 "Romance Standard Time": "Europe/Paris", "Israel Standard Time": "Asia/Jerusalem",
                 "India Standard Time": "Asia/Kolkata", "China Standard Time": "Asia/Shanghai",
                 "Tokyo Standard Time": "Asia/Tokyo", "AUS Eastern Standard Time": "Australia/Sydney",
                 "E. Australia Standard Time": "Australia/Brisbane", "New Zealand Standard Time": "Pacific/Auckland"}
        from .schedule import hidden_console
        result = subprocess.run(["tzutil", "/g"], capture_output=True, text=True, **hidden_console())
        if result.returncode == 0:
            candidates.append(zones.get(result.stdout.strip(), ""))
    else:
        local = str(Path("/etc/localtime").resolve())
        if "/zoneinfo/" in local:
            candidates.append(local.split("/zoneinfo/", 1)[1])
        if Path("/etc/timezone").is_file():
            candidates.append(Path("/etc/timezone").read_text().strip())
    candidates.append(getattr(datetime.now().astimezone().tzinfo, "key", ""))
    for candidate in candidates:
        try:
            ZoneInfo(candidate)
            return candidate
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return None


def ask_timezone(p):
    detected = detected_timezone()
    if detected and p.yes(f"Your system time zone appears to be {detected}. Use it?", True):
        return detected
    p.say("Choose a nearby city in the same time zone. You can also enter an IANA name such as Europe/Paris.")
    zones = sorted(available_timezones())
    def search(value):
        matches = [z for z in zones if value and value.lower().replace(" ", "_") in z.lower()]
        if not matches:
            raise ValueError("No matching city found. Try a nearby major city or UTC.")
        return matches
    matches = p.ask("City or time zone", validate=search)
    return matches[p.choose("Which time zone?", matches)]


def domain_rule(domain):
    return r"^https?://" + re.escape(domain) + r"(?::\d+)?(?:[/?#]|$)"


def item_rule(kind, text):
    """Escape a locally selected item, never treating its text as a regex."""
    return domain_rule(text) if kind == "url" else "^" + re.escape(text) + "$" if kind == "app" else re.escape(text)


def clockify_http(key):
    return JsonHTTP("https://api.clockify.me/api/v1", {"X-Api-Key": valid_key(key)}, "Clockify")


def verify_key(key):
    http = clockify_http(key)
    http.request("GET", "/user")
    return http


def workspaces(http):
    rows = http.request("GET", "/workspaces")
    if not rows:
        raise UserError("No Clockify workspaces found. Create one in Clockify and try again.")
    return rows


def remote_projects(http, workspace):
    base = "/workspaces/" + quote(workspace, safe="") + "/projects"
    return Clockify({}, [], http)._pages(base, {"archived": "false"})


def activity_hosts(buckets):
    return sorted(b[len("aw-watcher-window_"):] for b in buckets if b.startswith("aw-watcher-window_"))


def recent_activity(source, now):
    activity = source.fetch(now - timedelta(days=7), now)
    if not activity.windows or not activity.afk:
        raise UserError("No recent window or AFK activity found. Let ActivityWatch record some work, then try again.")
    return activity


def coverage(activity, config, start, end):
    slices = active_slices(activity, config.projects, start, end)
    return (sum(s.minutes for s in slices if s.project is not None), sum(s.minutes for s in slices))


def save_settings(collected, output=print):
    """Save a validated snapshot after the caller has obtained approval."""
    path, original, text, key, http, pending, raw = collected
    parse_config(tomllib.loads(text), path)
    current = path.read_text(encoding="utf-8") if path.exists() else None
    if current != original:
        raise UserError("The config changed during setup. Nothing overwritten; run setup again.")
    if key:
        save_key(key, output)
    for name in pending:
        base = "/workspaces/" + quote(raw["destination"]["workspace"], safe="") + "/projects"
        rows = remote_projects(http, raw["destination"]["workspace"])
        if any(r["name"] == name for r in rows):
            raise UserError(f"Clockify already has a project named '{name}'. Run setup again and select it.")
        row = next(r for r in raw["projects"] if r["name"] == name)
        http.request("POST", base, {"name": name, "isPublic": True,
                     "billable": row["agreement"]["billing"] != "none", "color": "#2196F3"})
        output(f"Created Clockify project '{safe(name)}'. It remains there if you quit later.")
    atomic_write(path, text)
    output(f"Saved {path}.")
    return load_config(path)


def activity_items(activity, start, end, limit=20):
    domains = sorted({urlsplit(str(e.data.get("url", ""))).hostname for e in activity.web
                      if urlsplit(str(e.data.get("url", ""))).scheme in ("http", "https")
                      and urlsplit(str(e.data.get("url", ""))).hostname})
    projects = [Project(d, d, "", False, {"url": [re.compile(domain_rule(d), re.I)]}) for d in domains]
    counts = Counter()
    for row in active_slices(activity, projects, start, end):
        if row.app:
            counts[("app", row.app)] += row.minutes
        if row.title:
            counts[("title", row.title)] += row.minutes
        if row.project is not None:
            counts[("url", domains[row.project])] += row.minutes
    return counts.most_common(limit)


def title_keyword(title, project):
    words = re.findall(r"\w+", title)
    for word in re.findall(r"\w+", project):
        if len(word) >= 3 and word.lower() in {w.lower() for w in words}:
            return word
    boring = {"google", "chrome", "mozilla", "firefox", "microsoft", "edge", "safari", "document", "untitled"}
    return max((w for w in words if len(w) >= 3 and w.lower() not in boring), key=len, default=title)


def picked_rules(p, items, name):
    p.say("Pick apps or website domains when they belong entirely to this project. "
          "An app rule includes every use of that app. Use a title keyword for shared apps.")
    for i, ((kind, text), minutes) in enumerate(items, 1):
        label = "website" if kind == "url" else kind
        p.say(f"  {i}. {label}: {text[:85]}{'...' if len(text) > 85 else ''} ({minutes:.1f} min)")
    p.say("These categories overlap; their times must not be added together.")
    def picks(value):
        try:
            result = list(dict.fromkeys(int(v) - 1 for v in value.replace(",", " ").split()))
        except ValueError:
            raise ValueError("Enter item numbers separated by spaces.") from None
        if not result or any(i < 0 or i >= len(items) for i in result):
            raise ValueError("Choose one or more numbers from the list.")
        return result
    selected = p.ask("Which numbers belong to this project?", validate=picks)
    rules = {"app": [], "url": [], "title": []}
    for i in selected:
        (kind, text), _ = items[i]
        if kind == "title":
            p.say(f"Window title: {text}")
            def keyword(value):
                nonempty(value)
                if value.casefold() not in text.casefold():
                    raise ValueError("Use a distinctive word or phrase contained in this title.")
                return value
            text = p.ask("Confirm a distinctive keyword or phrase for this project", title_keyword(text, name), keyword)
        rule = item_rule(kind, text)
        if rule not in rules[kind]:
            rules[kind].append(rule)
    return {k: v for k, v in rules.items() if v}


def ask_agreement(p):
    billing = ("hourly", "flat", "retainer", "none")[p.choose("How is this project billed?",
               ["Hourly", "Flat monthly", "Retainer with cap", "Not billed"])]
    result = {"billing": billing}
    p.say("Flat monthly and retainer agreements track time without calculating an hourly charge.")
    rate = p.ask("Agreed hourly rate (leave blank to skip)", validate=lambda v: number(v, optional=True))
    if rate is not None:
        result["rate"] = rate
    def currency(value):
        if value and not re.fullmatch(r"[A-Za-z]{3}", value):
            raise ValueError("Enter a three-letter currency code, such as CAD, or leave blank to skip.")
        return value.upper()
    unit = p.ask("Agreed currency (leave blank to skip)", validate=currency)
    if unit:
        result["currency"] = unit
    result["count_breaks_up_to_minutes"] = p.ask("Count short breaks up to how many minutes?", 0, lambda v: number(v, whole=True))
    p.say("The break limit includes exactly that many minutes. Only observed away gaps inside a merged block count.")
    p.say("Calls may look like away time when you are listening. Counting them still requires a matching project, "
          "a recognized call app or title, and away-time evidence.")
    result["count_calls_when_away"] = p.yes("Count calls while you are away from the keyboard?")
    result["round_to_minutes"] = (0, 6, 15, 30)[p.choose("Round each entry's duration?", ["No rounding", "6 minutes", "15 minutes", "30 minutes"])]
    if result["round_to_minutes"]:
        result["rounding"] = ("nearest", "up")[p.choose("How should durations be rounded?", ["Nearest", "Up"])]
    else:
        result["rounding"] = "nearest"
    cap = p.ask("Monthly cap in hours (leave blank for no cap)", validate=lambda v: number(v, optional=True))
    if cap is not None:
        result["monthly_cap_hours"] = cap
    return result


def toml_value(value):
    # JSON basic strings, booleans, numbers and lists are valid for these TOML values.
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def project_text(row):
    text = "\n[[projects]]\n"
    text += "".join(f"{key} = {toml_value(value)}\n" for key, value in row.items() if key != "agreement")
    text += "[projects.agreement]\n"
    return text + "".join(f"{key} = {toml_value(value)}\n" for key, value in row.get("agreement", {}).items())


def config_text(raw):
    text = f"timezone = {toml_value(raw['timezone'])}\n"
    for table in ("activitywatch", "blocks", "policy", "destination"):
        if table in raw:
            text += f"\n[{table}]\n" + "".join(f"{k} = {toml_value(v)}\n" for k, v in raw[table].items())
    return text + "".join(project_text(p) for p in raw["projects"])


def agreement_summary(row, blocks):
    agreement = row.agreement
    rate = f"{agreement['rate']:.2f} {agreement.get('currency', '(currency not set)')}/h" if "rate" in agreement else "rate not set"
    return (f"{row.name}: {row.description}; {'billable' if row.billable else 'not billed'}; "
            f"{agreement.get('billing', 'billing not set')}; {rate}; "
            f"breaks up to {agreement['count_breaks_up_to_minutes']} min; "
            f"away calls {'count' if agreement['count_calls_when_away'] else 'do not count'}; "
            f"rounding {agreement.get('round_to_minutes', blocks['round_to_minutes'])} min ({agreement['rounding']}); "
            f"monthly cap {agreement.get('monthly_cap_hours', 'none')} hours")


def append_projects(original, raw, initial_count):
    text = original.rstrip() + "\n"
    old_aw = tomllib.loads(original).get("activitywatch", {})
    extra = {k: v for k, v in raw["activitywatch"].items() if k not in old_aw and k != "url"}
    if extra:
        fields = "".join(f"{k} = {toml_value(v)}\n" for k, v in extra.items())
        header = re.search(r"(?m)^\s*\[activitywatch\][^\n]*\n", text)
        if header:
            text = text[:header.end()] + fields + text[header.end():]
        else:
            text += "\n[activitywatch]\n" + fields
    return text + "".join(project_text(r) for r in raw["projects"][initial_count:])


class Wizard:
    def __init__(self, prompts, explicit=None, add_project=False):
        self.p = prompts
        self.explicit = explicit
        self.add_project = add_project
        self.cache = {}
        self.now = datetime.now(timezone.utc)
        self.saved = False

    def cached(self, key, callback):
        if key not in self.cache:
            self.cache[key] = callback()
        return self.cache[key]

    def source(self, settings):
        p = self.p
        source = ActivityWatch(settings)
        while True:
            try:
                buckets = self.cached(("buckets", settings["url"]), lambda: source.http.request("GET", "/buckets/"))
                hosts = activity_hosts(buckets)
                if not settings.get("hostname") and hosts:
                    settings["hostname"] = hosts[p.choose("Which computer's activity?", hosts)] if len(hosts) > 1 else hosts[0]
                p.say(source.check())
                return source
            except UserError as exc:
                p.say(str(exc))
                p.say("ActivityWatch records your apps and away time locally so autohours can suggest timesheets. "
                      "Download and open it from https://activitywatch.net/downloads/ and enable the window and AFK watchers.")
                if not p.yes("Open ActivityWatch, then retry?", True):
                    raise Quit
                self.cache.pop(("buckets", settings["url"]), None)

    def clockify(self):
        p = self.p
        existing = read_key()
        key = ""
        if existing:
            try:
                self.cached(("key", existing), lambda: verify_key(existing))
                if p.yes("A saved CLOCKIFY_API_KEY is valid. Keep it?", True):
                    key = existing
            except UserError:
                p.say("The saved key could not be verified. You can enter a replacement or quit and try later.")
        while not key:
            p.say("In Clockify, open Profile settings, then API, then Generate. Copy the key. "
                  "Paste it only at this hidden prompt, never in chat. It will be saved separately when you confirm setup.")
            candidate = p.ask("Clockify API key (hidden)", secret=True, validate=valid_key)
            try:
                self.cached(("key", candidate), lambda: verify_key(candidate))
                key = candidate
            except UserError:
                p.say("That key could not be verified. Check it and your connection, then retry or type quit.")
        return key, self.http(key)

    @staticmethod
    def http(key):
        return clockify_http(key)

    def collect(self):
        p = self.p
        path = config_path(self.explicit).resolve()
        original = path.read_text(encoding="utf-8") if path.exists() else None
        adding = self.add_project
        if adding and original is None:
            raise UserError("No existing config found. Run autohours setup first.")
        if original is not None and not adding:
            choice = p.choose(f"Settings already exist at {path}. What would you like to do?",
                              ["Edit by adding a project", "Start over", "Quit"])
            adding = choice == 0
            if choice == 2:
                raise Quit
        raw = tomllib.loads(original) if adding else {"activitywatch": {"url": "http://localhost:5600"}, "projects": []}
        if adding:
            load_config(path)
        raw.setdefault("activitywatch", {}).setdefault("url", "http://localhost:5600")
        source = self.source(raw["activitywatch"])
        if not adding:
            raw["timezone"] = ask_timezone(p)
        zone = ZoneInfo(raw["timezone"])
        key, http, workspace_name = None, None, ""
        if not adding:
            kind = ("clockify", "csv")[p.choose("Where should timesheets go?", ["Clockify", "Spreadsheet (CSV)"], 2)]
            raw["destination"] = {"type": kind}
            if kind == "csv":
                def csv_path(value):
                    target = Path(nonempty(value)).expanduser().resolve()
                    if target.is_dir() or not target.parent.is_dir():
                        raise ValueError("Choose a CSV filename inside an existing folder.")
                    return str(target)
                raw["destination"]["path"] = p.ask("Where should the CSV file be saved?", str(Path.home() / "timesheet.csv"), csv_path)
        if raw["destination"]["type"] == "clockify":
            key, http = self.clockify()
            spaces = self.cached(("workspaces", key), lambda: workspaces(http))
            if not spaces:
                raise UserError("No Clockify workspaces found. Create one in Clockify and run setup again.")
            if adding:
                identifier = resolve(spaces, raw["destination"]["workspace"], "Workspace")
                workspace = next(s for s in spaces if s["id"] == identifier)
            else:
                workspace = spaces[p.choose("Which Clockify workspace?", [s["name"] for s in spaces])]
                raw["destination"]["workspace"] = workspace["id"]
            workspace_name = workspace["name"]
        start = self.now - timedelta(days=7)
        web_hosts = [meta.get("hostname") for b, meta in self.cache[("buckets", raw["activitywatch"]["url"])].items() if b.startswith("aw-watcher-web-")]
        if not adding and raw["activitywatch"].get("hostname") in web_hosts:
            if p.yes("Include website domains from your local ActivityWatch browser extension?"):
                raw["activitywatch"]["use_web"] = True
                source = self.source(raw["activitywatch"])
        p.say("The next list shows private local window titles from the last 7 days. Nothing is uploaded. "
              "Do not share terminal logs or screenshots without reviewing them.")
        activity = self.cached(("activity", json.dumps(raw["activitywatch"], sort_keys=True)), lambda: recent_activity(source, self.now))
        if not activity.windows or not activity.afk:
            raise UserError("No recent window or AFK activity found. Let ActivityWatch record some work, then run setup again.")
        items = activity_items(activity, start, self.now)
        if not items:
            raise UserError("No active time found in the last 7 days. Check the AFK watcher in ActivityWatch and try again.")
        initial_count = len(raw["projects"])
        pending = []
        while True:
            def project_name(value):
                nonempty(value)
                if value.lower() != "done" and any(row["name"] == value for row in raw["projects"]):
                    raise ValueError("That project is already configured. Choose another name.")
                if value.lower() == "done" and not raw["projects"]:
                    raise ValueError("Add at least one project first.")
                return value
            name = p.ask("What is the name of a client or project? (type done to finish)", validate=project_name)
            if name.lower() == "done":
                break
            row = {"name": name, **picked_rules(p, items, name)}
            if http:
                base = "/workspaces/" + quote(raw["destination"]["workspace"], safe="") + "/projects"
                remote = self.cached(("projects", key, base), lambda: remote_projects(http, raw["destination"]["workspace"]))
                while True:
                    choice = p.choose("Which Clockify project?", [r["name"] + " (" + r["id"] + ")" for r in remote] + ["Create a new project"])
                    if choice < len(remote):
                        target = remote[choice]["id"]
                        if any(r.get("destination_project", r["name"]) in (target, remote[choice]["name"]) for r in raw["projects"]):
                            p.say("That Clockify project is already used. Choose a distinct project.")
                            continue
                        row["destination_project"] = target
                        break
                    if not 2 <= len(name) <= 250:
                        raise UserError("Clockify project names need 2 to 250 characters. Type a longer name on the next setup run.")
                    if p.yes(f"Create '{name}' in '{workspace_name}' when saving? It will be visible to workspace members."):
                        pending.append(name)
                        break
            row["description"] = p.ask("Description to put on timesheet entries (no private titles)", name, nonempty)
            row["agreement"] = ask_agreement(p)
            raw["projects"].append(row)
            cfg = parse_config(deepcopy(raw), path)
            covered, total = coverage(activity, cfg, start, self.now)
            p.say(f"Rules now cover {covered:.1f} of {total:.1f} active minutes ({covered / total * 100 if total else 0:.1f}%) in the last 7 days. First matching project wins.")
        if not self.explicit and original is None:
            choice = p.choose("Where should settings be saved?", [f"User config folder: {user_config_dir()}", f"Current folder: {Path.cwd()}"])
            path = (user_config_dir() / CONFIG_NAME if choice == 0 else Path.cwd() / CONFIG_NAME).resolve()
        # Preserve all existing text, comments and relative paths when adding projects.
        text = append_projects(original, raw, initial_count) if adding else config_text(raw)
        cfg = parse_config(tomllib.loads(text), path)
        p.say(f"Save settings to {path}\nTime zone: {cfg.timezone}\nDestination: {workspace_name or cfg.destination['path']}")
        for row in cfg.projects:
            p.say("  " + agreement_summary(row, cfg.blocks))
        if pending:
            p.say("Clockify projects to create: " + ", ".join(pending))
        if not p.yes("Save these settings" + (" and replace the existing config?" if original is not None else "?")):
            raise Quit
        return path, original, text, key, http, pending, raw

    def commit(self, collected):
        config = save_settings(collected, self.p.output)
        self.saved = True
        self.p.checkpoint()
        return config

    def finish(self, config):
        from .cli import date_range, parser, run
        from .plugins import SOURCES
        from . import accepted
        p = self.p
        def command(*args):
            status = run(parser().parse_args(["--config", str(config.path), *args]))
            if status:
                raise UserError("That check needs attention. Settings are saved; fix the reported problem before syncing.")
        command("doctor")
        if config.destination["type"] == "clockify" and any(p.agreement.get("billing") == "hourly" and "rate" in p.agreement for p in config.projects):
            command("rates")
            if p.collect(lambda: p.yes("Apply the exact Clockify billable flags, rates and currencies shown above?")):
                command("rates", "--apply")
            p.checkpoint()
        p.say("Merged blocks group entries; excluded gaps are not billed. Rounding changes duration. "
              "Blocks under 10 minutes are normally omitted. Unmatched time stays unbilled. Explicit accepted work can count. "
              "Existing entries are skipped. Monthly caps in a local review can differ from sync, which reserves destination time.")
        today = datetime.now(timezone.utc).astimezone(config.timezone).date()
        day = str(today - timedelta(days=1))
        label = f"yesterday ({day})"
        a, b = date_range([day], config.timezone)
        result = build(SOURCES["activitywatch"](config).fetch(a, b), config.projects, config.blocks,
                       a, b, config.timezone, accepted.load(config))
        if not result.blocks:
            day = str(today)
            label = f"today ({day})"
        command("review", day)
        if not p.collect(lambda: p.yes(f"Does the review for {label} look right?")):
            p.say("Settings are saved. Run autohours setup --add-project to add matching rules, then review again.")
            return
        p.checkpoint()
        command("sync", day)
        target = config.destination.get("workspace", config.destination.get("path"))
        if not p.collect(lambda: p.yes(f"Write entries for {label} only to {target}?")):
            p.say("No entries written. Review and sync later when ready.")
            return
        command("sync", day, "--write")
        p.checkpoint()
        if p.collect(lambda: p.yes("Set up a daily run that automatically writes yesterday's timesheet?")):
            from .schedule import offer
            p.checkpoint()
            offer(config.path, p)


def setup(explicit=None, add_project=False, input_fn=None, secret_fn=None, output=print):
    p = Prompts(input_fn, secret_fn, output)
    wizard = Wizard(p, explicit, add_project)
    output("Welcome to autohours. Answer one question at a time. Type back to revisit the previous answer, "
           "or quit to stop. Ctrl+C also quits. No config is written until you confirm.")
    try:
        collected = p.collect(wizard.collect)
        config = wizard.commit(collected)
        wizard.finish(config)
        return 0
    except (Quit, KeyboardInterrupt, EOFError):
        output("Setup stopped. Your saved settings and any completed writes remain." if wizard.saved else
               "Setup stopped. No config was written. Any explicitly confirmed credential or Clockify changes remain.")
        return 0
