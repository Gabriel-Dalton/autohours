"""Private credential storage, separate from project configuration."""

import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

from .config import user_config_dir
from .models import UserError


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def credential_path():
    return user_config_dir() / "credentials"


def windows_key():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as entry:
            return str(winreg.QueryValueEx(entry, "CLOCKIFY_API_KEY")[0]).strip()
    except FileNotFoundError:
        return ""


def read_key():
    key = os.environ.get("CLOCKIFY_API_KEY", "").strip()
    if key:
        return key
    if sys.platform == "win32":
        # Scheduled tasks may inherit an older environment after setx.
        return windows_key()
    path = credential_path()
    if not path.exists():
        return ""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid():
        raise UserError(f"Clockify credentials must be your own regular file with permissions 600: {path}")
    return path.read_text(encoding="utf-8").strip()


def valid_key(key):
    if not key or len(key) > 1024 or any(c.isspace() or not c.isprintable() for c in key):
        raise UserError("The API key is not valid. Copy only the key from Clockify Profile settings.")
    return key


def save_key(key, output=print):
    valid_key(key)
    if sys.platform == "win32":
        result = subprocess.run(["setx", "CLOCKIFY_API_KEY", key], capture_output=True, text=True)
        if result.returncode:
            # Never include the command or captured output: both can contain the key.
            raise UserError("Could not save the Clockify key in your Windows user environment.")
        output("Saved CLOCKIFY_API_KEY in your Windows user environment and this process. "
               "To remove it, open 'Edit environment variables for your account' and delete CLOCKIFY_API_KEY; "
               "then close this terminal. You can also revoke it in Clockify Profile settings.")
    else:
        path = credential_path()
        atomic_write(path, key + "\n")  # mkstemp creates mode 600 before any secret is written.
        path.chmod(0o600)
        output(f"Saved the key in {path} (permissions 600) and this process. "
               "To remove it, delete that file and unset CLOCKIFY_API_KEY if you set it in your shell. "
               "You can also revoke it in Clockify Profile settings.")
    os.environ["CLOCKIFY_API_KEY"] = key
