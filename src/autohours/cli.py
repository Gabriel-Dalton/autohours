import argparse
from datetime import date, datetime, time, timedelta, timezone
from importlib.resources import files
from pathlib import Path
import sys

from . import APP_NAME, CONFIG_NAME
from . import accepted
from .config import config_path, load_config
from .destinations import sync
from .models import UserError
from .pipeline import apply_caps, build, classify
from .review import html_review, text_review
from .plugins import DESTINATIONS, SOURCES


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UserError(f"{message}. Run '{APP_NAME} --help' for usage.")


def date_range(values, zone, now=None):
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(zone).date()

    def parse(value):
        if value == "today":
            return today
        if value == "yesterday":
            return today - timedelta(days=1)
        try:
            if len(value) != 10:
                raise ValueError
            return date.fromisoformat(value)
        except ValueError:
            raise UserError(f"Unknown date '{value}'. Use today, yesterday, or YYYY-MM-DD.") from None

    if len(values) > 2:
        raise UserError("Use one date or START END. The end date is included.")
    first = parse(values[0]) if values else today
    last = parse(values[-1]) if values else today
    if last < first:
        raise UserError("The end date must be on or after the start date.")
    try:
        start = datetime.combine(first, time(), zone).astimezone(timezone.utc)
        end = datetime.combine(last + timedelta(days=1), time(), zone).astimezone(timezone.utc)
    except (OverflowError, ValueError):
        raise UserError("Date is outside the supported range. Choose a normal calendar date.") from None
    return start, end


def safe(value):
    return "".join(c if c.isprintable() else " " for c in str(value))


def show_unmatched(result):
    print(f"Unmatched: {sum(result.unmatched.values()):.1f} minutes (never written)")
    for (app, title), minutes in result.unmatched.most_common(10):
        print(f"  {minutes:7.1f} min  {safe(app)} | {safe(title)}")


def parser():
    root = Parser(prog=APP_NAME, description="Review local activity before writing timesheet entries.")
    root.add_argument("--config", metavar="PATH")
    commands = root.add_subparsers(dest="command", required=True, parser_class=Parser)
    commands.add_parser("init", help="Create a starter config without overwriting")
    commands.add_parser("doctor", help="Check config, watchers and destination")
    setup = commands.add_parser("setup", help="Set up timesheets by answering questions")
    setup.add_argument("--add-project", action="store_true", help="Add a project to existing settings")
    schedule = commands.add_parser("schedule", help="Remove the approved daily schedule")
    schedule.add_argument("--remove", action="store_true", required=True)
    rates = commands.add_parser("rates", help="Compare Clockify project agreements")
    rates.add_argument("--apply", action="store_true")
    accept = commands.add_parser("accept", help="Accept explicit work regardless of AFK")
    accept.add_argument("values", nargs="*", metavar="DATE START END")
    accept.add_argument("--project")
    accept.add_argument("--note", default="")
    accept.add_argument("--remove", metavar="ID")
    listing = commands.add_parser("accepted")
    listing.add_argument("date", nargs="?")
    for command in ("preview", "sync", "unmatched", "review"):
        sub = commands.add_parser(command)
        sub.add_argument("dates", nargs="*", metavar="DATE")
        if command == "sync":
            sub.add_argument("--write", action="store_true", help="Actually write the reviewed blocks")
        if command in ("preview", "review"):
            sub.add_argument("--html", metavar="PATH")
            sub.add_argument("--titles", action="store_true", help="Include private window titles")
            sub.add_argument("--verbose", action="store_true", help="Show all blocks and activity detail")
    rules = commands.add_parser("rules")
    tests = rules.add_subparsers(dest="rules_command", required=True, parser_class=Parser)
    test = tests.add_parser("test")
    test.add_argument("title")
    test.add_argument("--app", default="")
    test.add_argument("--url", default="")
    return root


def run(args):
    if args.command == "sync" and args.write:
        from .locking import writer_lock
        with writer_lock(config_path(args.config)):
            return _run(args)
    return _run(args)


def _run(args):
    if args.command == "setup":
        from .setup import setup
        return setup(args.config, args.add_project)
    if args.command == "schedule":
        from .schedule import remove
        remove()
        return 0
    if args.command == "init":
        path = Path(args.config).expanduser() if args.config else Path.cwd() / CONFIG_NAME
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(files("autohours").joinpath("starter.toml").read_text(encoding="utf-8"))
        except FileExistsError:
            raise UserError(f"{path} already exists. Keeping your settings; edit it instead.") from None
        print(f"Created {path}. Set your timezone and projects, then run {APP_NAME} doctor.")
        return 0
    config = load_config(config_path(args.config))
    if args.command == "accept":
        if args.remove:
            if args.values or args.project or args.note:
                raise UserError("Use accept --remove ID by itself.")
            accepted.remove(config, args.remove)
            print(f"Removed accepted block {safe(args.remove)}. Destination entries are unchanged.")
        else:
            if len(args.values) != 3 or not args.project:
                raise UserError("Use accept DATE START END --project NAME [--note TEXT].")
            day = date_range(args.values[:1], config.timezone)[0].astimezone(config.timezone).date()
            item = accepted.add(config, day, *args.values[1:], args.project, args.note)
            print(f"Accepted {item.id}. Review before syncing.")
        return 0
    if args.command == "accepted":
        period = date_range([args.date], config.timezone) if args.date else None
        for item in accepted.load(config):
            if period is None or item.start < period[1] and item.end > period[0]:
                print(f"{item.id}  {item.start.astimezone(config.timezone).isoformat()} to {item.end.astimezone(config.timezone).isoformat()}  {safe(config.projects[item.project].name)}  {safe(item.note)}")
        return 0
    if args.command == "rates":
        if config.destination["type"] != "clockify":
            raise UserError("rates requires a Clockify destination.")
        from .rates import compare
        messages, failed = compare(DESTINATIONS["clockify"](config), args.apply)
        for message in messages:
            print(safe(message))
        return int(failed)
    if args.command == "rules":
        found = classify(config.projects, args.title, args.app, args.url)
        print("Unmatched" if found is None else f"Matches: {safe(config.projects[found].name)} (first matching project)")
        return 0
    source = SOURCES["activitywatch"](config)
    if args.command == "doctor":
        print("Config parses successfully.")
        failed = False
        for factory in (lambda: source, lambda: DESTINATIONS[config.destination["type"]](config)):
            try:
                print(factory().check())
            except UserError as exc:
                print(f"Fix: {exc}")
                failed = True
        return int(failed)
    if args.command == "unmatched" and len(args.dates) > 1:
        raise UserError("unmatched accepts one date. Run it separately for each day.")
    start, end = date_range(args.dates, config.timezone)
    end = min(end, datetime.now(timezone.utc))
    if start >= end:
        raise UserError("That period is in the future. Choose today or an earlier date.")
    has_caps = any("monthly_cap_hours" in (p.agreement or {}) for p in config.projects)
    month_start = start.astimezone(config.timezone).replace(day=1).astimezone(timezone.utc)
    fetch_start = month_start if has_caps and args.command in ("preview", "review") else start
    activity = source.fetch(fetch_start, end)
    corrections = accepted.load(config)
    result = build(activity, config.projects, config.blocks, fetch_start, end,
                   config.timezone, corrections, caps=args.command != "sync")
    if fetch_start != start:
        # Keep monthly allocation, but display only the requested dates.
        selected = build(activity, config.projects, config.blocks, start, end,
                         config.timezone, corrections, caps=False)
        selected.blocks = [b for b in result.blocks if b.start >= start]
        selected.reviews = [r for r in result.reviews if r.start >= start]
        result = selected
    destination = None
    if args.command == "sync":
        destination = DESTINATIONS[config.destination["type"]](config)
        destination.check()
        if has_caps:
            last = end.astimezone(config.timezone)
            month_end = (last.replace(day=28) + timedelta(days=4)).replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
            apply_caps(result, config.projects, config.timezone,
                       destination.logged(month_start, month_end), destination.existing(start, end))
    if args.command == "unmatched":
        show_unmatched(result)
    else:
        titles = getattr(args, "titles", False)
        verbose = getattr(args, "verbose", False)
        print(text_review(result, config.projects, config.timezone, titles, verbose))
        if has_caps and args.command != "sync":
            print("Caps use local activity from the start of the month. Sync checks logged destination time too.")
        if getattr(args, "html", None):
            Path(args.html).write_text(html_review(result, config.projects, config.timezone, titles, verbose), encoding="utf-8")
            print(f"Review saved to {args.html}.")
        if args.command == "sync":
            created, skipped = sync(destination, result.blocks, start, end, args.write)
            if args.write:
                print(f"Created {created}, skipped {skipped} (already logged).")
            else:
                print(f"Would create {created}, would skip {skipped} (already logged). Nothing written. Use --write to write.")
    return 0


def main(argv=None):
    # Windows consoles and redirected streams can use legacy code pages.
    # Keep their encoding, replacing only characters they cannot represent.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    try:
        return run(parser().parse_args(argv))
    except (UserError, OSError, UnicodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (KeyError, TypeError, ValueError) as exc:
        print("Error: Unexpected data from the config or service. Check your settings and service version.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Stopped. Preview again before retrying a write.", file=sys.stderr)
        return 1
