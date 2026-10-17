"""Explicitly approved, per-user daily schedules with an undo command."""

from dataclasses import dataclass
from datetime import date
import os
from pathlib import Path
import plistlib
import re
import shlex
import subprocess
import sys
from xml.etree import ElementTree

from .config import user_config_dir
from .credentials import atomic_write
from .models import UserError


TASK = "AutohoursDaily"
LABEL = "local.autohours.daily"
MARKER = " # autohours daily"


@dataclass
class Plan:
    commands: list[list[str]]
    path: Path | None = None
    content: str | None = None
    stdin: str | None = None
    log: Path | None = None
    previous_crontab: str | None = None

    def describe(self):
        lines = ["This replaces only autohours' daily schedule for this account."]
        if self.path:
            lines.extend([f"File: {self.path}", self.content])
        lines.extend(subprocess.list2cmdline(command) for command in self.commands)
        if self.stdin is not None:
            lines.extend(["New user crontab (other jobs are preserved):", self.stdin])
        if self.log:
            lines.append(f"Private log: {self.log}")
        return "\n".join(lines)


def clock(value):
    if not re.fullmatch(r"\d{1,2}:\d{2}", value):
        raise ValueError("Use a 24-hour time such as 06:00 or 18:30.")
    hour, minute = map(int, value.split(":"))
    if hour > 23 or minute > 59:
        raise ValueError("Use a time from 00:00 to 23:59.")
    return f"{hour:02}:{minute:02}"


def build_plan(config, at="06:00", platform=None, executable=None, home=None, directory=None, crontab="", uid=None, frozen=None):
    platform = platform or sys.platform
    home = Path(home) if home is not None else Path.home()
    directory = (Path(directory) if directory is not None else user_config_dir()).resolve()
    executable = str(executable or Path(sys.executable).resolve())
    config = str(Path(config).resolve())
    at = clock(at)
    if any(c in value for value in (executable, config, str(directory)) for c in "\r\n\0"):
        raise UserError("Schedule paths cannot contain line breaks or null characters.")
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    command = [executable] + ([] if frozen else ["-B", "-m", "autohours"])
    command += ["--config", config, "sync", "yesterday", "--write"]
    if platform == "win32":
        return Plan([["schtasks", "/Create", "/TN", TASK, "/SC", "DAILY", "/ST", at,
                      "/TR", subprocess.list2cmdline(command), "/IT", "/F"]], log=directory / "logs" / f"{date.today()}.log")
    log = directory / "logs" / f"{date.today()}.log"
    hour, minute = map(int, at.split(":"))
    if platform == "darwin":
        path = home / "Library/LaunchAgents" / (LABEL + ".plist")
        domain = f"gui/{os.getuid() if uid is None else uid}"
        data = {"Label": LABEL, "ProgramArguments": command,
                "StartCalendarInterval": {"Hour": hour, "Minute": minute},
                "StandardOutPath": "/dev/null", "StandardErrorPath": "/dev/null", "Umask": 0o077}
        return Plan([["launchctl", "bootstrap", domain, str(path)]], path,
                    plistlib.dumps(data, sort_keys=False).decode("utf-8"), log=log)
    # Cron interprets percent signs even inside shell quotes.
    # Cron does not inherit XDG_CONFIG_HOME from the setup terminal. Preserve
    # the location of the private credentials file without embedding the key.
    environment = "XDG_CONFIG_HOME=" + shlex.quote(str(directory.parent)) + " "
    # The entry point writes dated logs itself; avoid a second unbounded log.
    job = ("umask 077; " + environment + shlex.join(command) + " >> /dev/null 2>&1").replace("%", r"\%")
    preserved = [line for line in crontab.splitlines() if not line.endswith(MARKER)]
    content = "\n".join(preserved + [f"{minute} {hour} * * * {job}{MARKER}"]) + "\n"
    return Plan([["crontab", "-"]], stdin=content, log=log, previous_crontab=crontab)


def execute(command, input=None):
    try:
        result = subprocess.run(command, input=input, capture_output=True, text=True, **hidden_console())
    except OSError:
        raise UserError(f"Could not start {command[0]}. Check that the system scheduling tool is installed.") from None
    if result.returncode:
        raise UserError(f"{command[0]} could not update the schedule. Check your account permissions and try again.")
    return result


def hidden_console():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def enabled():
    """Read the actual scheduler, including jobs installed by the text wizard."""
    if sys.platform == "win32":
        result = subprocess.run(["schtasks", "/Query", "/TN", TASK, "/XML"], capture_output=True,
                                text=True, **hidden_console())
        if result.returncode:
            return False
        try:
            root = ElementTree.fromstring(result.stdout)
            flags = [node.text for node in root.iter() if node.tag.endswith("}Enabled") or node.tag == "Enabled"]
            return all(value != "false" for value in flags)
        except ElementTree.ParseError:
            raise UserError("Could not read the nightly task status. Check Windows Task Scheduler.") from None
    if sys.platform == "darwin":
        result = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"], capture_output=True, text=True)
        return result.returncode == 0
    return any(line.endswith(MARKER) for line in read_crontab().splitlines())


def read_crontab():
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True, env={**os.environ, "LC_ALL": "C"})
    except OSError:
        raise UserError("The crontab tool is unavailable. Install your distribution's cron package to schedule runs.") from None
    if result.returncode and not (result.returncode == 1 and "no crontab for" in result.stderr.lower()):
        raise UserError("Could not read your crontab. No schedule was changed.")
    return result.stdout if result.returncode == 0 else ""


def install(plan, platform=None):
    platform = platform or sys.platform
    if plan.previous_crontab is not None and read_crontab() != plan.previous_crontab:
        raise UserError("Your crontab changed after the preview. Nothing overwritten; run setup again.")
    if plan.log:
        plan.log.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(plan.log, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        os.close(descriptor)
        plan.log.chmod(0o600)
    if plan.path:
        if plan.path.exists():
            # Unload before replacing the plist; a failure preserves the old file.
            execute(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"])
        atomic_write(plan.path, plan.content)
    for command in plan.commands:
        execute(command, plan.stdin)


def offer(config, prompts):
    def collect():
        prompts.say("The time uses your computer's clock. The job writes yesterday only and does not backfill missed days. "
                    "Only one writer for this config can run at once. Remove it with autohours schedule --remove.")
        at = prompts.ask("Daily run time (24-hour clock)", "06:00", clock)
        cron = read_crontab() if sys.platform not in ("win32", "darwin") else ""
        plan = build_plan(config, at, crontab=cron)
        prompts.say(plan.describe())
        if sys.platform == "darwin" and plan.path.exists():
            prompts.say(f"First unload: launchctl bootout gui/{os.getuid()}/{LABEL}")
        return plan if prompts.yes("Create this schedule and allow automatic daily writes?") else None
    plan = prompts.collect(collect)
    if plan:
        install(plan)
        prompts.output("Daily schedule created. To undo it, run autohours schedule --remove.")


def remove():
    if sys.platform == "win32":
        execute(["schtasks", "/Delete", "/TN", TASK, "/F"])
    elif sys.platform == "darwin":
        path = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
        if path.exists():
            execute(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"])
            path.unlink()
    else:
        previous = read_crontab()
        content = "\n".join(line for line in previous.splitlines() if not line.endswith(MARKER))
        execute(["crontab", "-"], content + "\n" if content else "")
    print("Removed the autohours daily schedule. Your settings and timesheets remain.")
