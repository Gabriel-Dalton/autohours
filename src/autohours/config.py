import os
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


def config_path(explicit=None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    local = Path.cwd() / CONFIG_NAME
    if local.exists():
        return local
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME / CONFIG_NAME


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
        raise UserError(f"No config found at {path}. Run '{APP_NAME} init' first.") from None
    except tomllib.TOMLDecodeError as exc:
        raise UserError(f"Config is not valid TOML: {exc}") from None
    _keys(raw, ["timezone", "activitywatch", "blocks", "destination", "projects"], "config")
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
        _keys(row, ["name", "destination_project", "description", "billable", "title", "app", "url"], "projects")
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
        projects.append(Project(name, target, description, row.get("billable", False), rules))
    return Config(zone, aw, blocks, dest, projects, path)
