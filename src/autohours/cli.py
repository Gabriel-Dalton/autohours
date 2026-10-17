import argparse
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from importlib.resources import files
from pathlib import Path
import sys

from . import APP_NAME, CONFIG_NAME
from .config import config_path, load_config
from .destinations import sync
from .models import UserError
from .pipeline import build, classify
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


def preview(result, zone):
    grouped = defaultdict(list)
    for block in result.blocks:
        grouped[block.project].append(block)
    if not grouped:
        print("No matching blocks. Check your rules, minimum block length and AFK watcher.")
    for name, blocks in grouped.items():
        print(f"{safe(name)}: {sum(b.minutes for b in blocks):.1f} minutes")
        for block in blocks:
            a = block.start.astimezone(zone).isoformat(timespec="seconds")
            b = block.end.astimezone(zone).isoformat(timespec="seconds")
            print(f"  {a} to {b}  {block.minutes:.1f} min  {safe(block.description)}")
    if result.discarded_minutes:
        print(f"Filtered out: {result.discarded_minutes:.1f} minutes (minute conflicts, short blocks or rounding)")
    show_unmatched(result)


def parser():
    root = Parser(prog=APP_NAME, description="Review local activity before writing timesheet entries.")
    root.add_argument("--config", metavar="PATH")
    commands = root.add_subparsers(dest="command", required=True, parser_class=Parser)
    commands.add_parser("init", help="Create a starter config without overwriting")
    commands.add_parser("doctor", help="Check config, watchers and destination")
    for command in ("preview", "sync", "unmatched"):
        sub = commands.add_parser(command)
        sub.add_argument("dates", nargs="*", metavar="DATE")
        if command == "sync":
            sub.add_argument("--write", action="store_true", help="Actually write the reviewed blocks")
    rules = commands.add_parser("rules")
    tests = rules.add_subparsers(dest="rules_command", required=True, parser_class=Parser)
    test = tests.add_parser("test")
    test.add_argument("title")
    test.add_argument("--app", default="")
    test.add_argument("--url", default="")
    return root


def run(args):
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
    result = build(source.fetch(start, end), config.projects, config.blocks, start, end, config.timezone)
    if args.command == "unmatched":
        show_unmatched(result)
    else:
        preview(result, config.timezone)
        if args.command == "sync":
            destination = DESTINATIONS[config.destination["type"]](config)
            destination.check()
            created, skipped = sync(destination, result.blocks, start, end, args.write)
            if args.write:
                print(f"Created {created}, skipped {skipped} (already logged).")
            else:
                print(f"Would create {created}, would skip {skipped} (already logged). Nothing written. Use --write to write.")
    return 0


def main(argv=None):
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
