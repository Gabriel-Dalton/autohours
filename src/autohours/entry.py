"""One entry point for pip, python -m, and the windowed packaged app."""

import sys

from . import cli
from .runlog import config_id, logging, record
from .config import config_path


def attach_console():
    """A windowed Windows build may inherit a parent console without streams."""
    if sys.platform != "win32" or sys.stdout is not None:
        return
    import ctypes
    kernel = ctypes.windll.kernel32
    if kernel.GetConsoleWindow() or kernel.AttachConsole(-1):
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return cli.main(["gui"])
    if getattr(sys, "frozen", False):
        try:
            attach_console()
        except OSError:
            pass  # Logging still works if the parent console has closed.
    unattended = getattr(sys, "frozen", False) or ("sync" in args and "--write" in args)
    if unattended and "gui" not in args:
        try:
            parsed = cli.parser().parse_args(args)
        except cli.UserError:
            parsed = None  # Let cli.main render its usual argument error.
        except SystemExit as exc:
            return exc.code  # Help and version print and exit; there is no run to log.
        try:
            with logging():
                if parsed is not None:
                    record("Run config: " + config_id(config_path(parsed.config)))
                    # The schedule runs without a terminal; someone typing the same command is a manual run.
                    typed = sys.stdin is not None and sys.stdin.isatty()
                    kind = "nightly" if parsed.command == "sync" and parsed.dates == ["yesterday"] and parsed.write and not typed else "manual"
                    record("Run kind: " + kind)
                result = cli.main(args)
                record(f"Run finished: {'success' if result == 0 else 'needs attention'}")
                return result
        except OSError:
            if sys.stderr is not None:
                print("Error: Could not open the private run log. Check your user config folder permissions.", file=sys.stderr)
            return 1
    return cli.main(args)
