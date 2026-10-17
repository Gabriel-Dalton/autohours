"""Private dated logs for unattended runs, with a thirty-day retention window."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta
import os
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
