"""Private, explicit corrections stored beside the user's config."""

from dataclasses import dataclass
from datetime import datetime, time, timezone
import json
import os
from pathlib import Path
import tempfile
import tomllib
from uuid import uuid4

from .models import UserError, iso, overlaps, timestamp


@dataclass
class Accepted:
    id: str
    start: datetime
    end: datetime
    project: int
    note: str = ""


def path_for(config):
    return config.path.resolve().with_name("autohours.accepted.toml")


def load(config):
    path = path_for(config)
    if not path.exists():
        return []
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        if set(raw) - {"accepted"}:
            raise ValueError
        result = []
        names = [p.name for p in config.projects]
        for row in raw.get("accepted", []):
            if set(row) - {"id", "start", "end", "project", "note"}:
                raise ValueError
            if not isinstance(row.get("start"), str) or not isinstance(row.get("end"), str):
                raise ValueError
            if row.get("project") not in names:
                continue  # Left by a hand edit; saving clients in the app tidies these away.
            item = Accepted(row["id"], timestamp(row["start"]), timestamp(row["end"]),
                            names.index(row["project"]), row.get("note", ""))
            if not isinstance(item.id, str) or not item.id or not isinstance(item.note, str) or item.end <= item.start:
                raise ValueError
            if any(old.id == item.id or overlaps((old.start, old.end), (item.start, item.end)) for old in result):
                raise ValueError
            result.append(item)
        return sorted(result, key=lambda item: item.start)
    except (ValueError, KeyError, TypeError):
        raise UserError(f"Invalid accepted time in {path}. Check IDs, projects, timestamps and overlapping blocks.") from None


def _serialize(item, config):
    values = {"id": item.id, "start": iso(item.start), "end": iso(item.end),
              "project": config.projects[item.project].name, "note": item.note}
    return "\n[[accepted]]\n" + "".join(f"{key} = {json.dumps(value, ensure_ascii=False)}\n" for key, value in values.items())


def local_time(day, value, zone):
    try:
        clock = time.fromisoformat(value)
        naive = datetime.combine(day, clock.replace(tzinfo=None))
        if clock.tzinfo is not None:
            moment = datetime.combine(day, clock).astimezone(timezone.utc)
            if moment.astimezone(zone).replace(tzinfo=None) != naive:
                raise ValueError
            return moment
        candidates = {naive.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
                      for fold in (0, 1)}
        candidates = {v for v in candidates if v.astimezone(zone).replace(tzinfo=None) == naive}
        if len(candidates) != 1:
            raise ValueError
        return candidates.pop()
    except ValueError:
        raise UserError("Use a valid local HH:MM time. For a repeated DST hour include its offset, such as 01:30-07:00.") from None


def add(config, day, start, end, project, note=""):
    names = [p.name for p in config.projects]
    if project not in names:
        raise UserError("Unknown project. Use a configured project name.")
    a, b = local_time(day, start, config.timezone), local_time(day, end, config.timezone)
    if b <= a or b > datetime.now(timezone.utc):
        raise UserError("Accepted time must end after its start on the same date and cannot be in the future.")
    rows = load(config)
    if any(overlaps((a, b), (r.start, r.end)) for r in rows):
        raise UserError("Accepted time overlaps another accepted block. Remove that block first.")
    item = Accepted(uuid4().hex[:12], a, b, names.index(project), note)
    with path_for(config).open("a", encoding="utf-8") as stream:
        stream.write(_serialize(item, config))
    return item


def _raw_rows(path):
    if not path.exists():
        return []
    try:
        rows = tomllib.loads(path.read_text(encoding="utf-8")).get("accepted", [])
        if not isinstance(rows, list) or not all(isinstance(row, dict) and isinstance(row.get("project"), str)
                                                 and isinstance(row.get("id"), str) for row in rows):
            raise ValueError
        return rows
    except (ValueError, UnicodeError):
        raise UserError(f"Invalid accepted time in {path}. Check IDs, projects, timestamps and overlapping blocks.") from None


def _write_rows(path, rows):
    text = "".join("\n[[accepted]]\n" + "".join(f"{key} = {json.dumps(value, ensure_ascii=False)}\n" for key, value in row.items())
                   for row in rows)
    # Atomic replacement beside the private file, without touching the config.
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def plan_client_changes(config_path, renames, names, removed=()):
    """Rows after dropping removed clients, renaming clients (old name to new) and dropping any
    client no longer in the settings. Removed clients are dropped first, so a client renamed to
    a removed client's name never inherits that client's time.

    Returns (path, rows, removed client names), or None when nothing changes."""
    path = Path(config_path).resolve().with_name("autohours.accepted.toml")
    rows = _raw_rows(path)
    gone = {row["project"] for row in rows if row["project"] in removed}
    updated = [{**row, "project": renames.get(row["project"], row["project"])} for row in rows if row["project"] not in removed]
    gone |= {row["project"] for row in updated if row["project"] not in names}
    kept = [row for row in updated if row["project"] in names]
    if kept == rows:
        return None
    return path, kept, sorted(gone)


def apply_client_changes(plan):
    if plan:
        _write_rows(plan[0], plan[1])


def remove(config, identifier):
    load(config)  # Refuse to rewrite a file that does not validate.
    path = path_for(config)
    rows = _raw_rows(path)
    remaining = [row for row in rows if row.get("id") != identifier]
    if len(rows) == len(remaining):
        raise UserError(f"Accepted ID '{identifier}' was not found.")
    _write_rows(path, remaining)
