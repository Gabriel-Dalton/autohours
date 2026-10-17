from types import SimpleNamespace
from threading import Event
import time

import pytest

pytest.importorskip("tkinter")
from autohours import desktop, gui, setup, theme
from test_desktop import hidden_root, session
from test_setup import services


def drain(root, app):
    deadline = time.monotonic() + 3
    while app.busy and time.monotonic() < deadline:
        root.update()
        time.sleep(.01)
    assert not app.busy


def test_timezone_detected_enter_and_back_navigation(hidden_root, tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "detected_timezone", lambda: "America/Vancouver")
    monkeypatch.setattr(desktop.Session, "hosts", lambda _: ["example-computer"])
    monkeypatch.setattr(desktop.Session, "check_buckets", lambda _: "Window and away time available.")
    app = gui.App(hidden_root, session(tmp_path))
    drain(hidden_root, app)
    assert app.zone.get() == "America/Vancouver"
    assert app.zone_summary.cget("text") == "Vancouver (America/Vancouver), detected"
    app.change_zone()
    assert app.enter(SimpleNamespace(widget=app.zone_box)) == "break"
    assert app.step == 1 and app.session.raw["timezone"] == "America/Vancouver"
    drain(hidden_root, app)
    assert app.nav_buttons[0].cget("text").startswith("✓")
    assert isinstance(app.nav_buttons[2], gui.ttk.Label)
    app.nav_buttons[0].invoke()
    assert app.step == 0 and app.zone.get() == "America/Vancouver"


def test_activity_computer_enter_after_automatic_check(hidden_root, tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "detected_timezone", lambda: "UTC")
    monkeypatch.setattr(desktop.Session, "hosts", lambda _: ["example-computer"])
    monkeypatch.setattr(desktop.Session, "check_buckets", lambda _: "Available")
    app = gui.App(hidden_root, session(tmp_path))
    drain(hidden_root, app)
    app.show_step(1)
    drain(hidden_root, app)
    assert app.aw_ready and app.host.get() == "example-computer"
    hidden_root.deiconify()
    hidden_root.update()
    app.host_box.focus_force()
    hidden_root.update()
    assert hidden_root.focus_get() == app.host_box
    app.host_box.event_generate("<Return>")
    hidden_root.update()
    assert app.step == 2


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def test_work_disables_only_controls_and_restores_states(hidden_root, tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "detected_timezone", lambda: None)
    app = gui.App(hidden_root, session(tmp_path))
    drain(hidden_root, app)
    controls = [factory(app.page) for factory in (gui.ttk.Button, gui.ttk.Entry,
                gui.ttk.Combobox, gui.ttk.Checkbutton, gui.ttk.Radiobutton,
                gui.ttk.Treeview, gui.ttk.Scale)]
    controls[2].state(["readonly"])
    controls[3].state(["disabled"])
    labels = [app.label("Synthetic label")]
    labels.extend(w for parent in (app.footer, app.sidebar) for w in descendants(parent)
                  if isinstance(w, gui.ttk.Label))
    previous = [w.state() for w in controls]
    release = Event()
    try:
        app.work(lambda: release.wait(2), lambda _: None)
        assert all("disabled" in w.state() for w in controls)
        assert all("disabled" not in w.state() for w in labels)
        assert "disabled" not in app.page.state()
        assert app.spinner.cget("style") == "Footer.TLabel"
        assert app.enter(SimpleNamespace(widget=controls[0])) is None
    finally:
        release.set()
        drain(hidden_root, app)
    assert [w.state() for w in controls] == previous


def test_lazy_activity_read_allows_enter_and_survives_navigation(hidden_root, tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "detected_timezone", lambda: None)
    value = session(tmp_path)
    release = Event()
    calls = []
    def read(settings):
        calls.append(settings)
        release.wait(2)
        return object(), [(("app", "Synthetic editor"), 60)]
    monkeypatch.setattr(value, "read_activity", read)
    app = gui.App(hidden_root, value)
    drain(hidden_root, app)
    assert not calls
    app.show_step(5)
    try:
        assert app.activity_loading and not app.busy
        assert app.coverage_label.cget("text") == "Reading your last 7 days of activity..."
        assert "disabled" not in app.default.state()
        assert app.enter(SimpleNamespace(widget=app.page)) == "break"
        assert app.step == 6
    finally:
        release.set()
        deadline = time.monotonic() + 3
        while app.activity_loading and time.monotonic() < deadline:
            hidden_root.update()
            time.sleep(.01)
    assert not app.activity_loading
    assert value.items == [(("app", "Synthetic editor"), 60)]
    assert app.step == 6


@pytest.mark.parametrize("dark", [False, True])
def test_every_rendered_style_has_disabled_palette_map(hidden_root, tmp_path, monkeypatch, dark):
    monkeypatch.setattr(theme, "system_dark", lambda: dark)
    monkeypatch.setattr(gui.App, "work", lambda *args: None)
    monkeypatch.setattr(gui.App, "read_activity", lambda *args: None)
    app = gui.App(hidden_root, session(tmp_path))
    style = gui.ttk.Style(hidden_root)
    for step in (*range(8), None):
        app.show_home() if step is None else app.show_step(step)
        for widget in descendants(hidden_root):
            if not isinstance(widget, gui.ttk.Widget):
                continue
            name = widget.cget("style") or widget.winfo_class()
            if name in ("TScrollbar", "TProgressbar", "TScale"):
                name = str(widget.cget("orient")).title() + "." + name
            assert name in theme.DISABLED_SURFACES
            assert style.lookup(name, "background", ("disabled",)) == app.colors[theme.DISABLED_SURFACES[name]]


@pytest.mark.parametrize("kind", ["entry", "combo", "check", "radio", "page", "text", "dropdown"])
def test_enter_routing(hidden_root, tmp_path, monkeypatch, kind):
    monkeypatch.setattr(gui.App, "work", lambda *args: None)
    monkeypatch.setattr(gui.App, "read_activity", lambda *args: None)
    app = gui.App(hidden_root, session(tmp_path))
    actions = []
    app.default.configure(command=lambda: actions.append("primary"))
    factories = {"entry": gui.ttk.Entry, "combo": gui.ttk.Combobox,
                 "check": gui.ttk.Checkbutton, "radio": gui.ttk.Radiobutton,
                 "page": gui.ttk.Frame, "text": gui.tk.Text, "dropdown": gui.ttk.Combobox}
    widget = factories[kind](app.page)
    widget.pack()
    hidden_root.deiconify()
    hidden_root.update()
    widget.focus_force()
    hidden_root.update()
    if kind == "dropdown":
        widget.configure(values=("One", "Two"), state="readonly")
        hidden_root.tk.call("ttk::combobox::Post", widget)
        hidden_root.update()
        assert app.enter(SimpleNamespace(widget=widget)) is None
        hidden_root.tk.call("ttk::combobox::Unpost", widget)
    else:
        widget.event_generate("<Return>")
        hidden_root.update()
    assert actions == ([] if kind in ("text", "dropdown") else ["primary"])
    if kind == "text":
        assert widget.get("1.0", "end-1c") == "\n"


def test_sidebar_skips_restore_and_done_links(hidden_root, tmp_path, monkeypatch):
    monkeypatch.setattr(gui.App, "work", lambda *args: None)
    monkeypatch.setattr(gui.App, "read_activity", lambda *args: None)
    app = gui.App(hidden_root, session(tmp_path))
    app.visited.update((0, 1, 2, 3, 4))
    app.show_step(5)
    for index in (3, 4):
        row = app.nav_buttons[index]
        assert isinstance(row, gui.ttk.Label)
        assert row.cget("text").startswith("-  ") and "Skipped" in row.cget("text")
    assert str(app.nav_buttons[0].cget("cursor")) == "hand2"
    assert isinstance(app.nav_buttons[6], gui.ttk.Label)
    app.go_back_to(2)
    app.destination.set("clockify")
    assert all("Skipped" not in row.cget("text") for row in app.nav_buttons)
    app.destination.set("csv")
    assert "Skipped" in app.nav_buttons[3].cget("text")
    style = gui.ttk.Style(hidden_root)
    assert str(style.lookup("Pending.Nav.TLabel", "borderwidth")) == "0"
    assert style.lookup("Nav.TButton", "background", ("active",)) != style.lookup("Nav.TButton", "background")


def test_first_project_activity_preview(hidden_root, tmp_path, monkeypatch):
    monkeypatch.setattr(gui.App, "work", lambda *args: None)
    monkeypatch.setattr(gui.App, "read_activity", lambda *args: None)
    value = session(tmp_path)
    value.raw["projects"] = []
    value.items = [(("app", "Editor"), 60), (("url", "example.test"), 30)]
    app = gui.App(hidden_root, value)
    app.show_step(5)
    buttons = [w for w in descendants(app.page) if isinstance(w, gui.ttk.Button)]
    first = next(w for w in buttons if w.cget("text") == "Add your first project")
    assert first.cget("style") == "Primary.TButton"
    checks = [w for w in descendants(app.item_panel) if isinstance(w, gui.ttk.Checkbutton)]
    assert len(checks) == 2 and all("disabled" in w.state() for w in checks)
    checks[0].invoke()
    assert value.raw["projects"] == []
    app.search.set("EXAMPLE")
    assert len([w for w in descendants(app.item_panel) if isinstance(w, gui.ttk.Checkbutton)]) == 1
    value.add_project("Example", "Work")
    app.show_step(5)
    checks = [w for w in descendants(app.item_panel) if isinstance(w, gui.ttk.Checkbutton)]
    assert all("disabled" not in w.state() for w in checks)
    checks[0].invoke()
    assert value.raw["projects"][0]["app"] == ["^Editor$"]


def test_timezone_fallback_and_saved_choice_not_overridden(hidden_root, tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "detected_timezone", lambda: None)
    app = gui.App(hidden_root, session(tmp_path))
    drain(hidden_root, app)
    assert app.zone.get() == "UTC" and "detected" not in app.zone_summary.cget("text")
    app.session.original = "saved"
    app.zone_initialized = True
    app.session.raw["timezone"] = "Europe/London"
    monkeypatch.setattr(setup, "detected_timezone", lambda: pytest.fail("Saved zone must be preserved"))
    app.show_step(0)
    assert app.zone.get() == "Europe/London"


@pytest.mark.parametrize("dark", [False, True])
@pytest.mark.parametrize("scale", [1.25, 1.5])
def test_scaled_screens_and_palette(hidden_root, tmp_path, monkeypatch, dark, scale):
    hidden_root.tk.call("tk", "scaling", scale * 96 / 72)
    monkeypatch.setattr(gui.window, "metrics", lambda root: (scale, (0, 0, 1920, 1040)))
    monkeypatch.setattr(theme, "system_dark", lambda: dark)
    monkeypatch.setattr(gui.App, "work", lambda *args: None)
    monkeypatch.setattr(gui.App, "read_activity", lambda *args: None)
    value = session(tmp_path)
    value.spaces = [{"id": "workspace", "name": "Example workspace"}]
    value.items = [(("app", "Editor"), 60), (("title", "A synthetic project title"), 30)]
    app = gui.App(hidden_root, value)
    assert app.colors == (theme.DARK if dark else theme.LIGHT)
    assert gui.ttk.Style(hidden_root).theme_use() == "clam"
    for step in range(8):
        app.show_step(step)
        app.resize(SimpleNamespace(width=app.px(640)))
        hidden_root.update_idletasks()
        assert app.page.winfo_children()
        assert app.content.winfo_width() <= app.px(760)
        assert app.default.cget("style") == "Primary.TButton"
    app.show_home()
    hidden_root.update_idletasks()
    assert len(app.nav_buttons) == 5
    app.focus_review()
    app.focus_nightly()
    assert app.home_at.get() == "06:00"


def test_search_filters_without_reassigning_and_agreement_drafts_survive(hidden_root, tmp_path, monkeypatch):
    monkeypatch.setattr(gui.App, "work", lambda *args: None)
    monkeypatch.setattr(gui.App, "read_activity", lambda *args: None)
    value = session(tmp_path)
    value.items = [(("app", "Editor"), 60), (("url", "example.test"), 30)]
    app = gui.App(hidden_root, value)
    app.show_step(5)
    before = setup.config_text(value.raw)
    app.search.set("EXAMPLE")
    assert setup.config_text(value.raw) == before
    labels = []
    def visit(widget):
        for child in widget.winfo_children():
            if isinstance(child, gui.ttk.Checkbutton):
                labels.append(child.cget("text"))
            visit(child)
    visit(app.item_panel)
    assert labels == ["example.test  ·  Website"]
    app.show_step(6)
    app.agreement_fields[0][1]["rate"].set("123")
    app.go_back_to(5)
    app.show_step(6)
    assert app.agreement_fields[0][1]["rate"].get() == "123"


def test_review_totals_do_not_write_and_preserve_time_spans(hidden_root, tmp_path, monkeypatch, services):
    monkeypatch.setattr(gui.App, "work", lambda *args: None)
    monkeypatch.setattr(gui.App, "read_activity", lambda *args: None)
    value = session(tmp_path)
    value.raw["projects"][0].update(app=["^Acme\\.App\\+$"],
        agreement={"billing": "hourly", "rate": 100, "currency": "CAD"})
    cfg, result = value.review("2026-10-16")
    app = gui.App(hidden_root, value)
    app.focus_review()
    app.render_review("2026-10-16", cfg, result)
    text = []
    tables = []
    def visit(widget):
        for child in widget.winfo_children():
            if isinstance(child, gui.ttk.Label):
                text.append(child.cget("text"))
            if isinstance(child, gui.ttk.Treeview):
                tables.append(child)
            visit(child)
    visit(app.review_panel)
    assert "100.00 CAD" in text and "1.00" in text and "Entries to write" in text
    assert " to " in tables[0].item(tables[0].get_children()[0], "values")[1]
    assert all(method == "GET" for _, method, _, _ in services.calls)
    assert not (tmp_path / "times.csv").exists()


def test_nightly_time_readback_is_read_only(monkeypatch):
    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.setattr(desktop.schedule, "enabled", lambda: True)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="<Task><Triggers><CalendarTrigger>"
            "<StartBoundary>2026-10-17T07:45:00</StartBoundary></CalendarTrigger></Triggers></Task>")
    monkeypatch.setattr(desktop.subprocess, "run", run)
    assert desktop.nightly_status() == "On at 07:45"
    assert calls == [["schtasks", "/Query", "/TN", desktop.schedule.TASK, "/XML"]]
    monkeypatch.setattr(desktop.schedule, "enabled", lambda: False)
    assert desktop.nightly_status() == "Off"


@pytest.mark.parametrize("scale", [1, 1.25, 1.5])
def test_activity_rows_and_project_actions_stay_inline(hidden_root, tmp_path, monkeypatch, scale):
    monkeypatch.setattr(gui.window, "metrics", lambda root: (scale, (0, 0, 1920, 1040)))
    hidden_root.tk.call("tk", "scaling", scale * 96 / 72)
    monkeypatch.setattr(gui.App, "work", lambda *args: None)
    monkeypatch.setattr(gui.App, "read_activity", lambda *args: None)
    value = session(tmp_path)
    value.raw["projects"][0]["app"] = []
    value.items = [(("app", "WindowsTerminal.exe"), 60), (("title", "✳ Example title"), 30)]
    app = gui.App(hidden_root, value)
    app.show_step(5)
    hidden_root.deiconify()
    hidden_root.update()
    checks = [w for w in descendants(app.item_panel) if isinstance(w, gui.ttk.Checkbutton)]
    for check in checks:
        hours = next(w for w in check.master.winfo_children() if isinstance(w, gui.ttk.Label))
        assert check.grid_info()["row"] == hours.grid_info()["row"] == 0
        assert hours.cget("style") == "Helper.TLabel"
        assert hours.winfo_rootx() >= check.winfo_rootx() + check.winfo_width()
        assert check.master.winfo_height() <= app.px(38)
    assert app.projects.winfo_rootx() >= app.item_panel.winfo_rootx() + app.item_panel.winfo_width()
    buttons = [w for w in descendants(app.page) if isinstance(w, gui.ttk.Button)]
    actions = [next(w for w in buttons if w.cget("text") == text) for text in ("Add", "Move up", "Edit", "Remove")]
    assert len({w.winfo_rooty() for w in actions}) == 1
    assert actions[-1].winfo_rootx() + actions[-1].winfo_width() <= app.page.winfo_rootx() + app.page.winfo_width()
    refresh = next(w for w in buttons if w.cget("text") == "Refresh activity")
    assert refresh.cget("style") == "Link.TButton"
    assert refresh.master == app.item_panel.master
    app.search.set("Windows Terminal")
    checks = [w for w in descendants(app.item_panel) if isinstance(w, gui.ttk.Checkbutton)]
    assert len(checks) == 1
    checks[0].invoke()
    assert value.raw["projects"][0]["app"] == [r"^WindowsTerminal\.exe$"]
    app.search.set("Example title")
    check = next(w for w in descendants(app.item_panel) if isinstance(w, gui.ttk.Checkbutton))
    check.invoke()
    assert value.raw["projects"][0]["title"] == [setup.item_rule("title", "✳ Example title")]


@pytest.mark.parametrize("kind,raw,expected", [
    ("app", "WindowsTerminal.exe", "Windows Terminal  ·  App"),
    ("app", "chrome.exe", "Google Chrome  ·  App"),
    ("app", "WINWORD.EXE", "Word  ·  App"),
    ("app", "SomeHTTPTool.exe", "Some HTTP Tool  ·  App"),
    ("title", " ✳ ★ Weekly planning notes", "Weekly planning notes  ·  Window title"),
    ("url", "github.com", "github.com  ·  Website"),
])
def test_activity_display_names(kind, raw, expected):
    assert desktop.activity_label(kind, raw) == expected


@pytest.mark.parametrize("scale", [1, 1.25, 1.5])
def test_step_six_friendly_names_survive_layout(hidden_root, tmp_path, monkeypatch, scale):
    monkeypatch.setattr(gui.window, "metrics", lambda root: (scale, (0, 0, 1080, 1920)))
    hidden_root.tk.call("tk", "scaling", scale * 96 / 72)
    monkeypatch.setattr(theme, "system_dark", lambda: True)
    monkeypatch.setattr(gui.App, "work", lambda *args: None)
    monkeypatch.setattr(gui.App, "read_activity", lambda *args: None)
    value = session(tmp_path)
    value.items = [(("app", "WindowsTerminal.exe"), 60),
                   (("app", "chrome.exe"), 30),
                   (("title", "Synthetic activity " * 30), 15)]
    app = gui.App(hidden_root, value)
    app.show_step(5)  # The sixth user-visible step, Projects and rules.
    # Widgets only get real sizes once mapped, so show the root off screen.
    hidden_root.geometry("+-4000+-4000")
    hidden_root.deiconify()
    app.resize(SimpleNamespace(width=780))
    hidden_root.update()
    checks = [w for w in descendants(app.item_panel) if isinstance(w, gui.ttk.Checkbutton)]
    assert len(checks) == 3
    for check, start in zip(checks, ("Windows Terminal", "Google Chrome", "Synthetic")):
        assert check.master.winfo_width() > 100
        assert len(check.cget("text")) > 3
        assert check.cget("text").startswith(start)
    long_text = checks[-1].cget("text")
    assert "..." in long_text
    app.resize(SimpleNamespace(width=650))
    hidden_root.update()
    narrow_text = checks[-1].cget("text")
    assert len(narrow_text) < len(long_text)
    app.resize(SimpleNamespace(width=780))
    hidden_root.update()
    assert len(checks[-1].cget("text")) > len(narrow_text)
