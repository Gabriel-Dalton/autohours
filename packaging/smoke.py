"""Open a built app headlessly and screenshot its first screens: smoke.py OUT_DIR COMMAND..."""
import os
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    out, command = Path(sys.argv[1]), sys.argv[2:]
    out.mkdir(parents=True, exist_ok=True)
    config = Path(tempfile.mkdtemp()) / "autohours.toml"
    app = subprocess.Popen(command + ["--config", str(config), "gui"], stdout=subprocess.PIPE, text=True,
                           env={**os.environ, "AUTOHOURS_NO_WINDOW": "1"})
    lines = queue.Queue()
    threading.Thread(target=lambda: [lines.put(line) for line in app.stdout], daemon=True).start()
    try:
        url = ""
        while not url.startswith("Open autohours: "):
            url = lines.get(timeout=60)
        url = url.split(": ", 1)[1].strip()
        errors = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url)
            page.get_by_role("heading", name="Set up autohours").wait_for(timeout=15000)
            for scheme in ("light", "dark"):
                page.emulate_media(color_scheme=scheme)
                page.wait_for_timeout(300)
                page.screenshot(path=str(out / f"{sys.platform}-welcome-{scheme}.png"))
            page.get_by_role("button", name="Get started").click()
            page.get_by_role("heading", name="Connect ActivityWatch").wait_for(timeout=15000)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(out / f"{sys.platform}-activitywatch-dark.png"))
            browser.close()
        if errors:
            raise SystemExit("Page errors: " + "; ".join(errors))
        print("Smoke test passed")
    finally:
        app.terminate()
        try:
            app.wait(timeout=10)
        except subprocess.TimeoutExpired:
            app.kill()


if __name__ == "__main__":
    main()
