"""Offline contracts for the bundled Carbon assets."""

from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess
import tomllib
from xml.etree import ElementTree

from autohours import webapp
import pytest


WEB = Path(webapp.__file__).parent / "web"


def test_productive_motion_and_interruptible_value_animation():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed to execute the bundled JavaScript helpers")
    source = (WEB / "app.js").read_text(encoding="utf-8")
    helpers = source[source.index("function productiveEase("):source.index("function showError(")]
    checks = r'''
const assert = require("node:assert/strict");
assert.equal(productiveEase(-1), 0);
assert.equal(productiveEase(0), 0);
assert.equal(productiveEase(1), 1);
assert.equal(productiveEase(2), 1);
// At Bezier parameter t=0.5 the specified curve has x=0.3425, y=0.4625.
assert(Math.abs(productiveEase(0.3425) - 0.4625) < 0.00001);
let last = 0;
for (let i = 1; i <= 100; i++) {
  const next = productiveEase(i / 100);
  assert(next >= last && next <= 1);
  last = next;
}
let now = 0, sequence = 0;
const frames = new Map();
const preference = {matches: false};
globalThis.performance = {now: () => now};
globalThis.window = {matchMedia: query => {
  assert.equal(query, "(prefers-reduced-motion: reduce)"); return preference;
}};
globalThis.requestAnimationFrame = callback => { frames.set(++sequence, callback); return sequence; };
globalThis.cancelAnimationFrame = id => frames.delete(id);
function advance(time) {
  now = time;
  const pending = [...frames.values()]; frames.clear();
  pending.forEach(callback => callback(now));
}
const node = {isConnected: true};
let displayed;
animateValue(node, 100, value => { displayed = value; });
assert.equal(displayed, 0);
advance(120);
assert(displayed > 0 && displayed < 100);
const interrupted = displayed;
animateValue(node, 25, value => { displayed = value; });
assert.equal(displayed, interrupted);
assert.equal(frames.size, 1, "repeated updates cancel the older animation");
advance(240);
assert(displayed < interrupted && displayed > 25);
advance(360);
assert.equal(displayed, 25);
assert.equal(frames.size, 0);
preference.matches = true;
animateValue(node, 42, value => { displayed = value; });
assert.equal(displayed, 42);
assert.equal(frames.size, 0, "reduced motion paints the final value immediately");
preference.matches = false;
animateValue(node, 99, value => { displayed = value; });
preference.matches = true;
advance(400);
assert.equal(displayed, 99, "a changed preference stops an in-flight animation");
assert.equal(frames.size, 0);
preference.matches = false;
animateValue(node, 120, value => { displayed = value; });
node.isConnected = false;
advance(600);
assert.equal(displayed, 99, "detached screens are not updated");
assert.equal(frames.size, 0);
node.isConnected = true;
animateValue(node, 1, value => { displayed = value; }, 0.5);
assert.equal(displayed, 0.5, "progress bars accept fractional starting values");
advance(840);
assert.equal(displayed, 1);
'''
    subprocess.run([node, "--check", str(WEB / "app.js")], check=True, capture_output=True, text=True)
    subprocess.run([node, "-e", helpers + checks], check=True, capture_output=True, text=True)


def test_welcome_preview_and_strict_csp_contract():
    assert "style-src 'self';" in webapp.CSP
    assert "script-src 'self';" in webapp.CSP
    assert "'unsafe-inline'" not in webapp.CSP

    class Markup(HTMLParser):
        preview_hidden = False
        description = False

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            assert "style" not in attrs
            assert not any(key.startswith("on") for key in attrs)
            if tag == "script":
                assert attrs.get("src") == "/app.js"
            if attrs.get("class") == "preview-illustration":
                self.preview_hidden = attrs.get("aria-hidden") == "true"
            if attrs.get("class") == "visually-hidden":
                self.description = True

    parser = Markup()
    html = (WEB / "index.html").read_text(encoding="utf-8")
    parser.feed(html)
    assert parser.preview_hidden and parser.description
    for text in ("invoice-api - Visual Studio Code", "Homepage redesign - Figma",
                 "Acme Corp", "2h 15m", "Globex", "1h 30m", "Spotify: not billed"):
        assert text in html
    script = (WEB / "app.js").read_text(encoding="utf-8")
    assert not re.search(r'\.style\b|setAttribute\([\'\"]style[\'\"]', script)


def test_activity_pagination_and_nightly_notification_kind():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed to execute the bundled JavaScript helpers")
    source = (WEB / "app.js").read_text(encoding="utf-8")
    helpers = source[source.index("function activityPage("):source.index("function activityRows(")]
    checks = r'''
const assert = require("node:assert/strict");
const items = Array.from({length: 40}, (_, id) => ({id, name: `App ${id}`}));
assert.deepEqual(activityPage(items, "", false), {visible: items.slice(0, 12), total: 40});
assert.deepEqual(activityPage(items, "", true), {visible: items, total: 40});
assert.deepEqual(activityPage(items, "APP 39", false), {visible: [items[39]], total: 1});
assert.deepEqual(activityPage(items, "missing", false), {visible: [], total: 0});
assert.deepEqual(activityPage([], "", false), {visible: [], total: 0});
assert.equal(activityPage(items.slice(0, 12), "", false).visible.length, 12);
assert.equal(nightlyKind("Not run yet. Your first run will appear here."), "info");
for (const text of ["Today at 6:00 AM: wrote 5 entries, 2 h 45 min.",
                    "Today at 6:00 AM: wrote 0 entries, 0 min.", "Last run: completed."]) {
  assert.equal(nightlyKind(text), "success");
}
for (const text of ["could not reach ActivityWatch. Nothing was written.",
                    "could not reach Clockify. Some entries may have been written.",
                    "Clockify rejected access. Nothing was written. Check your key and permissions.",
                    "did not finish. Review the day before trying again.", "needs attention. Nothing was written."]) {
  assert.equal(nightlyKind("Today at 6:00 AM: " + text), "error");
}
assert.equal(nightlyKind("The recent run log could not be read."), "error");
'''
    subprocess.run([node, "-e", helpers + checks], check=True, capture_output=True, text=True)


def test_no_text_character_icons():
    for name in ("app.js", "index.html"):
        source = (WEB / name).read_text(encoding="utf-8")
        assert not set(source) & set("✓✕✔✗•◷▤◴○"), name


def test_sprite_references_exist():
    sprite = ElementTree.parse(WEB / "icons.svg")
    ids = {node.attrib["id"] for node in sprite.findall("{http://www.w3.org/2000/svg}symbol")}
    script = (WEB / "app.js").read_text(encoding="utf-8")
    # All dynamic <use> elements resolve through this explicit local href map.
    references = set(re.findall(r'"/icons\.svg#([\w-]+)"', script))
    assert references and references <= ids
    assert 'use.setAttribute("href", iconPaths[name])' in script
    assert set(re.findall(r'\bicon\("([\w-]+)"', script)) <= references

    class Uses(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == "use":
                href = dict(attrs)["href"]
                assert href.startswith("/icons.svg#")
                assert href.split("#", 1)[1] in ids

    Uses().feed((WEB / "index.html").read_text(encoding="utf-8"))


def test_fonts_and_licences_ship_in_both_packages():
    root = WEB.parents[2]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = config["tool"]["setuptools"]["package-data"]["autohours"]
    packaged = {path for pattern in patterns for path in WEB.parent.glob(pattern) if path.is_file()}
    expected = {WEB / "icons.svg", WEB / "icons-LICENSE.txt", WEB / "fonts/OFL.txt",
                WEB / "fonts/IBMPlexSans-Regular.woff2", WEB / "fonts/IBMPlexSans-SemiBold.woff2"}
    assert expected <= packaged
    for font in WEB.glob("fonts/*.woff2"):
        assert font.read_bytes().startswith(b"wOF2")

    # Execute only the spec's data collection with a synthetic PyInstaller import.
    # No analysis, cache, build, or executable output is created.
    import ast
    import sys
    spec = ast.parse((root / "packaging/autohours.spec").read_text(encoding="utf-8"))
    collection = []
    for node in spec.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "a" for t in node.targets):
            break
        collection.append(node)
    scope = {"Path": Path, "sys": sys, "SPECPATH": str(root / "packaging"), "collect_data_files": lambda _: []}
    exec(compile(ast.Module(body=collection, type_ignores=[]), "<spec-data>", "exec"), scope)
    bundled = {Path(src): Path(dest) for src, dest in scope["datas"]}
    for path in expected:
        assert bundled[path] == Path("autohours/web") / path.relative_to(WEB).parent
