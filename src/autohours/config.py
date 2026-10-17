import os
import math
from pathlib import Path
import re
import sys
import tomllib
from dataclasses import dataclass
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import APP_NAME, CONFIG_NAME
from .models import Project, UserError


@dataclass
class Config:
    timezone: ZoneInfo
    activitywatch: dict
    blocks: dict
    destination: dict
    projects: list[Project]
    path: Path
    policy: dict


POLICY = {"count_breaks_up_to_minutes": 0, "count_calls_when_away": False,
          "rounding": "nearest",
          "call_apps": ["Zoom", "Google Meet", "Microsoft Teams", "Slack huddle", "Discord"],
          "call_titles": ["Google Meet", "Microsoft Teams", "Slack huddle"]}


def agreement_table(table, label):
    _keys(table, ["billing", "rate", "currency", "count_breaks_up_to_minutes",
                  "count_calls_when_away", "round_to_minutes", "rounding",
                  "monthly_cap_hours", "call_apps", "call_titles"], label)
    for key in ("billing", "rounding"):
        allowed = ("hourly", "flat", "retainer", "none") if key == "billing" else ("nearest", "up")
        if key in table and table[key] not in allowed:
            raise UserError(f"{label}.{key} must be one of: {', '.join(allowed)}.")
    for key in ("rate", "monthly_cap_hours", "count_breaks_up_to_minutes", "round_to_minutes"):
        if key in table:
            value = table[key]
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise UserError(f"{label}.{key} must be a finite non-negative number.")
            if key.endswith("minutes") and (type(value) is not int or value > 1440):
                raise UserError(f"{label}.{key} must be a whole number from 0 to 1440.")
    if "currency" in table and (not isinstance(table["currency"], str) or not re.fullmatch(r"[A-Z]{3}", table["currency"])):
        raise UserError(f"{label}.currency must be a three-letter uppercase ISO currency code.")
    if "count_calls_when_away" in table and type(table["count_calls_when_away"]) is not bool:
        raise UserError(f"{label}.count_calls_when_away must be true or false.")
    for key in ("call_apps", "call_titles"):
        if key in table:
            values = table[key]
            if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
                raise UserError(f"{label}.{key} must be a list of non-empty regex strings.")
            try:
                for value in values:
                    re.compile(value)
            except re.error as exc:
                raise UserError(f"{label}.{key}: invalid regex: {exc}.") from None
    return table


def config_path(explicit=None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    local = Path.cwd() / CONFIG_NAME
    if local.exists():
        return local
    return user_config_dir() / CONFIG_NAME


def user_config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME


def _keys(table, allowed, label):
    if not isinstance(table, dict):
        raise UserError(f"{label} must be a TOML table.")
    extra = table.keys() - set(allowed)
    if extra:
        raise UserError(f"Unknown setting in {label}: {', '.join(sorted(extra))}. Check the example config. API keys belong only in CLOCKIFY_API_KEY.")


def _string(value, label):
    if not isinstance(value, str) or not value.strip():
        raise UserError(f"{label} must be a non-empty string.")
    return value


def load_config(path: Path) -> Config:
    try:
        with path.open("rb") as stream:
            raw = tomllib.load(stream)
    except FileNotFoundError:
        raise UserError(f"No config found at {path}. Run '{APP_NAME} setup' (or init for manual setup) first.") from None
    except tomllib.TOMLDecodeError as exc:
        raise UserError(f"Config is not valid TOML: {exc}") from None
    return parse_config(raw, path)


def parse_config(raw, path: Path) -> Config:
    """Validate in memory too, before the setup wizard writes anything."""
    _keys(raw, ["timezone", "activitywatch", "blocks", "destination", "projects", "policy"], "config")
    policy = {**POLICY, **agreement_table(raw.get("policy", {}), "policy")}
    name = _string(raw.get("timezone"), "timezone")
    try:
        zone = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise UserError(f"Timezone '{name}' is unavailable. Use an IANA name such as America/Vancouver. On Windows install timezone data: pip install tzdata (pipx: pipx inject {APP_NAME} tzdata).") from None
    aw = raw.get("activitywatch", {})
    _keys(aw, ["url", "hostname", "use_web"], "activitywatch")
    aw = aw.copy()
    aw.setdefault("url", "http://localhost:5600")
    parsed = urlsplit(_string(aw["url"], "activitywatch.url"))
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise UserError("activitywatch.url must be a local HTTP URL, such as http://localhost:5600.")
    if "hostname" in aw:
        _string(aw["hostname"], "activitywatch.hostname")
    aw.setdefault("use_web", False)
    if type(aw["use_web"]) is not bool:
        raise UserError("activitywatch.use_web must be true or false.")
    blocks = raw.get("blocks", {})
    _keys(blocks, ["merge_gap_minutes", "min_block_minutes", "round_to_minutes"], "blocks")
    blocks = {"merge_gap_minutes": 5, "min_block_minutes": 10, "round_to_minutes": 0, **blocks}
    for key, value in blocks.items():
        if type(value) is not int or not 0 <= value <= 1440:
            raise UserError(f"blocks.{key} must be a whole number from 0 to 1440.")
    dest = raw.get("destination", {})
    _keys(dest, ["type", "workspace", "path"], "destination")
    if dest.get("type") not in ("clockify", "csv"):
        raise UserError('destination.type must be "clockify" or "csv".')
    field = "workspace" if dest["type"] == "clockify" else "path"
    _string(dest.get(field), f"destination.{field}")
    if dest["type"] == "csv":
        dest["path"] = str(path.resolve().parent / Path(dest["path"]).expanduser())
    entries = raw.get("projects")
    if not isinstance(entries, list) or not entries:
        raise UserError("Add at least one [[projects]] section with match rules.")
    projects = []
    for row in entries:
        _keys(row, ["name", "destination_project", "description", "billable", "title", "app", "url", "agreement"], "projects")
        name = _string(row.get("name"), "project name")
        target = _string(row.get("destination_project", name), "destination_project")
        description = row.get("description", name)
        if not isinstance(description, str) or type(row.get("billable", False)) is not bool:
            raise UserError(f"Project '{name}' needs a string description and a true/false billable setting.")
        if any(p.name == name for p in projects):
            raise UserError(f"Project names must be unique: {name}.")
        rules = {}
        for field in ("title", "app", "url"):
            values = row.get(field, [])
            if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
                raise UserError(f"Project '{name}': {field} must be a list of non-empty regex strings.")
            try:
                rules[field] = [re.compile(v, re.IGNORECASE) for v in values]
            except re.error as exc:
                raise UserError(f"Project '{name}': invalid {field} regex: {exc}.") from None
        if not any(rules.values()):
            raise UserError(f"Project '{name}' needs at least one title, app or url rule.")
        agreement = {**policy, **agreement_table(row.get("agreement", {}), f"{name}.agreement")}
        billable = row.get("billable", False)
        if "billing" in agreement:
            billable = agreement["billing"] != "none"
        projects.append(Project(name, target, description, billable, rules, agreement))
    for project in projects:
        if "monthly_cap_hours" in project.agreement or "billing" in project.agreement:
            if sum(p.destination_project == project.destination_project for p in projects) > 1:
                raise UserError("Projects with billing agreements or caps need distinct destination projects.")
    return Config(zone, aw, blocks, dest, projects, path, policy)
