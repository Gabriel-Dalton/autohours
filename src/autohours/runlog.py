"""Private dated logs for unattended runs, with a thirty-day retention window."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta
import hashlib
import os
from pathlib import Path
import re
import sys

from .config import user_config_dir


class Tee:
    def __init__(self, log, console):
        self.log, self.console = log, console

    def write(self, value):
        self.log.write(value)
        self.log.flush()
        if self.console is not None:
            self.console.write(value)
        return len(value)

    def flush(self):
        self.log.flush()
        if self.console is not None:
            self.console.flush()


def log_directory():
    return user_config_dir() / "logs"


def config_id(path):
    """Identify the config without exposing its private filesystem path."""
    return hashlib.sha256(os.path.normcase(str(Path(path).expanduser().resolve())).encode("utf-8")).hexdigest()


def prune(directory, today):
    for path in directory.glob("*.log"):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.log", path.name):
            continue
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if day < today - timedelta(days=29):
            path.unlink()


@contextmanager
def logging(directory=None, today=None):
    directory = directory or log_directory()
    today = today or date.today()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    prune(directory, today)
    path = directory / f"{today}.log"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    path.chmod(0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
        with redirect_stdout(Tee(stream, sys.stdout)), redirect_stderr(Tee(stream, sys.stderr)):
            print(f"Run started: {datetime.now().isoformat(timespec='seconds')}")
            yield


def last_result(directory=None):
    directory = directory or log_directory()
    paths = sorted(p for p in directory.glob("*.log") if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.log", p.name) and p.stat().st_size)
    if not paths:
        return "No run recorded yet."
    path = paths[-1]
    # Read only the tail of an append-only daily log.
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - 8192))
        lines = stream.read().decode("utf-8", errors="replace").splitlines()
    results = [line for line in lines if line.startswith(("Created ", "Error:", "Run finished:", "Run started:"))]
    return f"{path.stem}: " + "\n".join(results[-3:]) if results else f"{path.stem}: Run has no completion result."


def last_summary(directory=None, today=None, config=None, nightly_only=False):
    """A short dashboard summary, without copying private preview text."""
    directory = directory or log_directory()
    today = today or date.today()
    paths = sorted(p for p in directory.glob("*.log") if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.log", p.name) and p.stat().st_size)
    empty = "Not run yet. Turn on Every morning below, or write a day yourself."
    marker = "Run config: " + config_id(config) if config is not None else None
    def matches(row):
        return (row and (marker is None or marker in row)
                and (not nightly_only or "Run kind: nightly" in row))
    lines = None
    for path in reversed(paths):
        # Stream records so a long preview cannot hide its start/config marker.
        latest, record = None, []
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                line = line.rstrip("\r\n")
                if line.startswith("Run started: "):
                    if matches(record):
                        latest = record
                    record = []
                # Keep only known result lines, never activity or traceback text.
                if line.startswith(("Run started: ", "Run config: ", "Run kind: ", "Run finished: ", "Wrote ", "Error: ", "Write phase started.")):
                    record.append(line)
        if matches(record):
            latest = record
        if latest:
            lines = latest
            break
    if lines is None:
        return empty
    try:
        started = datetime.fromisoformat(lines[0].removeprefix("Run started: "))
        label = "Today" if started.date() == today else started.strftime("%A, %B ") + str(started.day)
        label += f" at {started.hour % 12 or 12}:{started.minute:02d} {'AM' if started.hour < 12 else 'PM'}"
    except ValueError:
        label = "Last run"
    written = next((line for line in reversed(lines) if re.fullmatch(r"Wrote \d+ entries, \d+\.\d+ h\.", line)), None)
    if "Run finished: success" in lines and written:
        match = re.fullmatch(r"Wrote (\d+) entries, (\d+\.\d+) h\.", written)
        minutes = round(float(match[2]) * 60)
        duration = f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"
        return label + f": wrote {match[1]} entries, {duration}."
    if "Run finished: success" in lines:
        return label + ": completed."
    errors = "\n".join(line for line in lines if line.startswith("Error: "))
    before_write = (any(line.startswith("Run config: ") for line in lines)
                    and "Run finished: needs attention" in lines and "Write phase started." not in lines)
    outcome = "Nothing was written." if before_write else "Some entries may have been written. Review the day before trying again."
    if "Cannot reach ActivityWatch" in errors:
        return label + ": could not reach ActivityWatch. Nothing was written."
    if "Cannot reach Clockify" in errors:
        return label + ": could not reach Clockify. " + outcome
    if "Clockify returned HTTP 401" in errors or "Clockify returned HTTP 403" in errors:
        return label + ": Clockify rejected access. " + outcome + " Check your key and permissions."
    if "Run finished: needs attention" not in lines:
        return label + ": did not finish. Review the day before trying again."
    return label + ": needs attention. " + outcome
