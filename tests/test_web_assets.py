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
                    "Today at 6:00 AM: wrote 1 entry, 30 min.",
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
    assert 'use.setAttribute("href", spriteReady ? "#" + name : iconPaths[name])' in script
    assert set(re.findall(r'\bicon\("([\w-]+)"', script)) <= references

    class Uses(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == "use":
                href = dict(attrs)["href"]
                assert href.startswith("#")
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


def test_notification_sprite_and_closed_state_helpers():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed to execute the bundled JavaScript helpers")
    source = (WEB / "app.js").read_text(encoding="utf-8")
    helpers = source[source.index("async function loadIcons("):source.index("function buttonLabel(")]
    helpers += source[source.index("function notification("):source.index("function clearErrors(")]
    helpers += source[source.index("function closedScreen("):source.index('document.addEventListener("visibilitychange"')]
    checks = r'''
const assert = require("node:assert/strict");
class Node {
  constructor(tag = "div", attrs = {}, ...children) {
    this.tag = tag; this.attrs = {...attrs}; this.children = children.filter(v => v != null);
    this.dataset = {}; this.classList = {remove() {}}; this.namespaceURI = "http://www.w3.org/2000/svg";
  }
  setAttribute(k, v) { this.attrs[k] = v; }
  getAttribute(k) { return this.attrs[k]; }
  append(...nodes) { this.children.push(...nodes); }
  prepend(node) { this.children.unshift(node); }
  replaceChildren(...nodes) { this.children = nodes; }
  focus() { this.focused = true; }
  remove() { this.removed = true; }
  scrollIntoView() {}
}
const el = (...args) => new Node(...args);
const button = () => new Node("button");
const page = new Node(), toast = new Node(), footer = new Node();
const shell = new Node(), progress = new Node(), quit = new Node(), preview = new Node();
const staticUse = new Node("use", {href: "#time"});
const templateUse = new Node("use", {href: "#time"});
const document = {
  body: new Node(),
  querySelector: key => ({"#app-shell": shell, "#setup-progress": progress, "#quit": quit, ".welcome-preview": preview})[key],
  querySelectorAll: key => key === "use" ? [staticUse] : [{content: {querySelectorAll: () => [templateUse]}}],
  createElementNS: (ns, tag) => new Node(tag),
  importNode: root => new Node("svg")
};
let invalid = false;
class DOMParser {
  parseFromString(text, type) {
    assert.equal(type, "image/svg+xml");
    return {documentElement: {localName: "svg", namespaceURI: "http://www.w3.org/2000/svg"}, querySelector: () => invalid};
  }
}
let spriteReady = false, disconnected = false, token = "token", generation = 1;
let heartbeat = 12, awTimer = 13, primary = new Node(), beforeStepBack = () => {};
const sessionKey = "test";
const cleared = [];
const clearInterval = id => cleared.push(id), clearTimeout = id => cleared.push(id);
const sessionStorage = {removeItem: key => assert.equal(key, sessionKey)};
const iconPaths = {time: "/icons.svg#time", "error--filled": "/icons.svg#error--filled", "information--filled": "/icons.svg#information--filled", "warning--filled": "/icons.svg#warning--filled", "checkmark--filled": "/icons.svg#checkmark--filled"};
let calls = 0;
let fetch = async url => { calls++; assert.equal(url, "/icons.svg"); return {ok: true, text: async () => "sprite"}; };
(async () => {
  await loadIcons();
  assert.equal(calls, 1);
  assert.equal(spriteReady, true);
  assert.equal(document.body.children[0].attrs["aria-hidden"], "true");
  assert.equal(staticUse.attrs.href, "#time");
  assert.equal(templateUse.attrs.href, "#time");
  fetch = async () => { throw new Error("offline"); };
  assert.equal(icon("time").children[0].attrs.href, "#time", "icons remain local after shutdown");
  spriteReady = false;
  await loadIcons();
  assert.equal(staticUse.attrs.href, "/icons.svg#time");
  assert.equal(templateUse.attrs.href, "/icons.svg#time");
  assert.equal(icon("time").children[0].attrs.href, "/icons.svg#time");
  fetch = async () => ({ok: true, text: async () => "bad XML"}); invalid = true;
  await loadIcons(); assert.equal(spriteReady, false);
  assert.equal(document.body.children.length, 1, "invalid XML is not inserted");
  for (const kind of ["error", "warning", "info", "success"]) {
    const n = notification(kind, "Specific title", "Next step", true);
    assert.equal(n.attrs.role, kind === "error" ? "alert" : "status");
    assert.equal(n.children[0].attrs.class, "icon icon-20");
    assert.equal(n.children[1].children[0].tag, "strong");
    assert.equal(n.children[1].children[1].tag, "p");
    assert.equal(n.children[2].attrs["aria-label"], "Close notification");
  }
  notice("Specific failure", true);
  assert.deepEqual(toast.children[0].children[1].children[0].children, ["Specific failure"]);
  assert.equal(toast.children[0].children[1].children.length, 1);
  notice("Specific failure", true, "Try this next");
  assert.equal(toast.children[0].children[1].children.length, 2);
  let resolve;
  fetch = () => new Promise(done => { resolve = done; });
  const pending = api("state");
  closedScreen();
  resolve({ok: true, json: async () => ({saved: true})});
  await assert.rejects(pending, /autohours has closed/);
  assert.equal(shell.dataset.screen, "closed");
  assert.equal(token, ""); assert.equal(primary, null);
  assert.deepEqual(cleared, [12, 13]);
  assert(progress.hidden && footer.hidden && toast.hidden && quit.hidden);
  assert(preview.removed);
  const content = page.children[0];
  assert.equal(content.children[0].attrs.class, "icon icon-24");
  assert.deepEqual(content.children[1].children, ["autohours has closed"]);
  assert(content.children[1].focused);
  notice("Late failure", true); assert.equal(toast.children.length, 0);
  await beat(); assert.deepEqual(cleared, [12, 13]);
  disconnected = false; closedScreen(true);
  assert.deepEqual(page.children[0].children[1].children, ["This window has expired"]);
  disconnected = false; fetch = async () => { throw new Error("offline"); };
  await beat(); assert(disconnected);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    subprocess.run([node, "-e", helpers + checks], check=True, capture_output=True, text=True)


def test_neutral_notifications_and_no_accent_stripes():
    css = (WEB / "app.css").read_text(encoding="utf-8")
    assert "border-left:" not in css
    assert "border-inline-start:" not in css
    assert "border-top-color:" not in css
    notification = re.search(r"\.notification \{([^}]+)\}", css).group(1)
    assert "border: 1px solid var(--border-subtle-01)" in notification
    assert "--notification-background: var(--layer-01)" in notification
    assert ".notification-content strong { display: block; font-weight: 600; }" in css
    assert ".closed-state > .icon { color: var(--text-secondary);" in css
    script = (WEB / "app.js").read_text(encoding="utf-8")
    assert script.count("await loadIcons();") == 1
    assert '(async () => {\n  await loadIcons();' in script
