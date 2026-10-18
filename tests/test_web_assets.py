"""Offline contracts for the bundled Carbon assets."""

from html.parser import HTMLParser
from pathlib import Path
import re
import tomllib
from xml.etree import ElementTree

from autohours import webapp


WEB = Path(webapp.__file__).parent / "web"


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
