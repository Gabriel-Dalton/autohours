"""A small ttk front end. Workers never read or update Tk widgets."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from queue import Empty, Queue
import sys
from threading import Thread
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser
from zoneinfo import ZoneInfo, available_timezones

from . import schedule, setup, theme
from .desktop import Session, agreement, full_report, nightly_status, open_settings
from .models import UserError
from .review import reasons, span, text_review
from .runlog import last_result


STEPS = ("Welcome", "ActivityWatch", "Where timesheets go", "Clockify key",
         "Workspace", "Projects and rules", "Project agreements", "Check and finish")
SUBTITLES = ("Make time for the work that matters. Let's get your timesheets ready.",
             "Check that your apps and time away are being recorded locally.",
             "Choose where your reviewed timesheets will be saved.",
             "Connect your Clockify account with a private API key.",
             "Choose the workspace that holds your projects.",
             "Match your local activity to the projects you work on.",
             "Choose how time counts for each project.",
             "Save your settings, review your time, then choose what happens next.")


class App:
    def __init__(self, root, session):
        self.root, self.session = root, session
        self.busy = False
        self.queue = Queue()
        self.step = None
        self.reviewed = None
        self.selected_day = None
        self.saved = session.original is not None
        self.aw_ready = False
        self.agreement_fields = []
        self.agreement_drafts = {}
        self.visited = set()
        self.detected_zone = None
        self.home_view = 0
        self.zone_initialized = session.original is not None
        self.root.title("autohours")
        self.colors = theme.apply(root)
        self.icon = theme.icon(root, self.colors["accent"])
        self.scale = max(1, float(root.tk.call("tk", "scaling")) / (96 / 72))
        screen_width = max(640, root.winfo_screenwidth() - 64)
        screen_height = max(480, root.winfo_screenheight() - 100)
        self.root.geometry(f"{min(self.px(1040), screen_width)}x{min(self.px(760), screen_height)}")
        self.root.minsize(min(self.px(860), screen_width), min(self.px(540), screen_height))
        self.status = tk.StringVar(value="")
        self.sidebar = ttk.Frame(root, padding=(12, 24), width=self.px(220))
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        main = ttk.Frame(root, style="Page.TFrame")
        main.pack(fill="both", expand=True)
        viewport = ttk.Frame(main, style="Page.TFrame", padding=(12, 12))
        viewport.pack(fill="both", expand=True)
        viewport.columnconfigure(0, weight=1)
        viewport.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(viewport, highlightthickness=0, background=self.colors["page"])
        self.scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=self.canvas.yview)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.configure(yscrollcommand=self.update_scrollbar)
        self.content = ttk.Frame(self.canvas, padding=(20, 24), style="Page.TFrame")
        self.page_id = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self.resize)
        # Create footer controls after the page so Tab follows the visual order.
        self.footer = ttk.Frame(main, padding=(16, 12))
        self.footer.pack(side="bottom", fill="x", before=viewport)
        root.bind("<FocusIn>", self.reveal_focus, add=True)
        root.bind("<Return>", self.enter)
        self.enter_tag = "AutohoursPrimaryAction"
        root.bind_class(self.enter_tag, "<Return>", self.enter)
        root.bind("<MouseWheel>", self.scroll, add=True)
        root.bind("<Button-4>", self.scroll, add=True)
        root.bind("<Button-5>", self.scroll, add=True)
        root.bind("<Escape>", lambda _: self.cancel())
        root.protocol("WM_DELETE_WINDOW", self.cancel)
        root.report_callback_exception = lambda *args: self.error(args[1])
        self.default = None
        self.show_home() if self.saved else self.show_step(0)

    def px(self, value):
        return round(value * self.scale)

    def update_scrollbar(self, first, last):
        self.scrollbar.set(first, last)
        if self.content.winfo_reqheight() > self.canvas.winfo_height():
            self.scrollbar.grid(row=0, column=1, sticky="ns")
        else:
            self.scrollbar.grid_remove()

    def resize(self, event):
        width = min(event.width, self.px(760))
        self.canvas.itemconfigure(self.page_id, width=width)
        self.canvas.coords(self.page_id, max(0, (event.width - width) / 2), 0)

    def scroll(self, event):
        if event.widget.winfo_toplevel() != self.root or isinstance(event.widget, (tk.Text, ttk.Treeview, ttk.Combobox)):
            return
        if self.content.winfo_height() > self.canvas.winfo_height():
            direction = -1 if event.num == 4 or event.delta > 0 else 1
            self.canvas.yview_scroll(direction * 3, "units")
            return "break"

    def reveal_focus(self, event):
        widget = event.widget
        # Closed comboboxes consume Return in their class binding.
        if widget.winfo_toplevel() == self.root and not isinstance(widget, tk.Text):
            tags = widget.bindtags()
            if self.enter_tag not in tags:
                widget.bindtags((self.enter_tag,) + tags)
        if str(widget).startswith(str(self.content)):
            self.root.update_idletasks()
            y = widget.winfo_rooty() - self.content.winfo_rooty()
            top = self.canvas.canvasy(0)
            if y < top or y + widget.winfo_height() > top + self.canvas.winfo_height():
                self.canvas.yview_moveto(max(0, y - 30) / max(1, self.content.winfo_height()))

    def enter(self, event):
        if self.busy or event.widget.winfo_toplevel() != self.root:
            return
        if isinstance(event.widget, tk.Text):
            return
        if isinstance(event.widget, ttk.Combobox):
            popup = self.root.tk.call("ttk::combobox::PopdownWindow", event.widget)
            if self.root.tk.call("winfo", "ismapped", popup):
                return
        if isinstance(event.widget, ttk.Button):
            event.widget.invoke()
        elif self.default:
            self.default.invoke()
        return "break"

    def error(self, exc):
        self.status.set("Needs attention")
        message = str(exc) if isinstance(exc, (UserError, ValueError)) else (
            "That action could not finish. Check your connection and settings, then try again. "
            "Review the day again before retrying a write.")
        if self.step in (1, 3, 7):
            label = getattr(self, {1: "aw_label", 3: "key_label", 7: "doctor_label"}[self.step], None)
            if label is not None and label.winfo_exists():
                label.configure(text="✕ " + message, style="Danger.TLabel")
        messagebox.showerror("Needs attention", message, parent=self.root)

    def work(self, callback, done):
        if self.busy:
            return
        self.busy = True
        self.status.set("Working...")
        self.animate_work()
        states = []
        def disable(parent):
            for child in parent.winfo_children():
                if isinstance(child, ttk.Widget) and hasattr(child, "state"):
                    states.append((child, child.state()))
                    child.state(["disabled"])
                disable(child)
        disable(self.page)
        disable(self.footer)
        disable(self.sidebar)
        def worker():
            try:
                self.queue.put((True, callback()))
            except Exception as exc:
                self.queue.put((False, exc))
        Thread(target=worker, daemon=True).start()
        def poll():
            try:
                ok, value = self.queue.get_nowait()
            except Empty:
                self.root.after(75, poll)
                return
            self.busy = False
            self.root.after_cancel(self.spinner_after)
            self.spinner.configure(text="")
            self.status.set("" if ok else "Needs attention")
            for widget, previous in states:
                if widget.winfo_exists():
                    widget.state(["!disabled", *previous])
            if ok:
                done(value)
            else:
                self.error(value)
        self.root.after(75, poll)

    def animate_work(self, frame=0):
        self.spinner.configure(text=("◐", "◓", "◑", "◒")[frame % 4])
        self.spinner_after = self.root.after(120, lambda: self.animate_work(frame + 1))

    def clear(self, heading, subtitle=""):
        self.status.set("")
        for parent in (self.content, self.footer):
            for child in parent.winfo_children():
                child.destroy()
        self.default = None
        self.canvas.yview_moveto(0)
        self.label(heading, self.content, "Title.TLabel")
        self.label(subtitle, self.content, "Subtitle.TLabel").pack_configure(pady=(2, 18))
        self.page = self.card(self.content)
        self.render_sidebar()

    def card(self, parent=None, title=None):
        frame = ttk.Frame(parent or self.page, style="Card.TFrame", padding=18)
        frame.pack(fill="x", pady=(0, 14))
        if title:
            self.label(title, frame, "Heading.TLabel")
        return frame

    def label(self, text, parent=None, style="TLabel"):
        label = ttk.Label(parent or self.page, text=text, wraplength=self.px(640), justify="left", style=style)
        label.pack(anchor="w", fill="x", pady=3)
        label.bind("<Configure>", lambda event: label.configure(wraplength=max(200, event.width - 10)))
        return label

    def button(self, text, action, parent=None, style="Secondary.TButton"):
        button = ttk.Button(parent or self.page, text=text, command=action, style=style)
        button.pack(anchor="w", pady=5)
        return button

    def render_sidebar(self):
        for child in self.sidebar.winfo_children():
            child.destroy()
        self.label("autohours", self.sidebar, "Heading.TLabel").pack_configure(pady=(0, 26))
        self.nav_buttons = []
        rows = ("Welcome", "ActivityWatch", "Destination", "Clockify key", "Workspace", "Projects and rules",
                "Agreements", "Check and finish") if self.step is not None else (
                    "Home", "Review a day", "Projects and rules", "Nightly run", "Settings")
        for index, title in enumerate(rows):
            current = index == (self.step if self.step is not None else self.home_view)
            destination = (self.destination.get() if self.step == 2 and hasattr(self, "destination")
                           else self.session.raw["destination"]["type"])
            skipped = self.step is not None and not current and index in (3, 4) and destination == "csv"
            done = self.step is not None and index < self.step and index in self.visited and not skipped
            row = ttk.Frame(self.sidebar)
            row.pack(fill="x", pady=3)
            ttk.Frame(row, width=4, style="Accent.TFrame" if current else "TFrame").pack(side="left", fill="y")
            text = f"{'✓' if done else index + 1}  {title}" if self.step is not None else title
            action = (lambda index=index: self.go_back_to(index)) if self.step is not None else (
                self.show_home, self.focus_review, self.edit_projects, self.focus_nightly, self.settings)[index]
            if self.step is not None and (skipped or not done and not current):
                text = f"-  {title} (Skipped)" if skipped else text
                button = ttk.Label(row, text=text, style="Pending.Nav.TLabel", wraplength=self.px(164))
                button.pack(fill="x")
            else:
                button = self.button(text, action, row, "Current.Nav.TButton" if current else "Nav.TButton")
                button.pack_configure(fill="x", pady=0)
                if done or self.step is None:
                    button.configure(cursor="hand2")
            self.nav_buttons.append(button)

    def go_back_to(self, number):
        if self.busy or number >= self.step or number not in self.visited:
            return
        # Keep the same edits and secret clearing as the Back button.
        if self.step == 6:
            self.keep_agreement_drafts()
        if self.step == 3:
            self.secret.set("")
        self.show_step(number)

    def build_footer(self, text, action, back=None):
        for child in self.footer.winfo_children():
            child.destroy()
        self.footer.columnconfigure(1, weight=1)
        left = ttk.Button(self.footer, text="Back", command=back, style="Secondary.TButton")
        left.grid(row=0, column=0, padx=(0, 12))
        if back is None:
            left.state(["disabled"])
        status = ttk.Frame(self.footer)
        status.grid(row=0, column=1, sticky="ew")
        self.spinner = ttk.Label(status, text="", width=2, style="Helper.TLabel")
        self.spinner.pack(side="left", padx=(0, 8))
        label = ttk.Label(status, textvariable=self.status, style="Helper.TLabel", wraplength=180)
        label.pack(fill="x", expand=True)
        label.bind("<Configure>", lambda event: label.configure(wraplength=max(50, event.width)))
        ttk.Button(self.footer, text="Cancel" if self.step is not None else "Close", command=self.cancel,
                   style="Secondary.TButton").grid(row=0, column=2, padx=8)
        self.default = ttk.Button(self.footer, text=text, command=action, style="Primary.TButton")
        self.default.grid(row=0, column=3)

    def entry(self, label, value="", parent=None, choices=None, masked=False):
        parent = parent or self.page
        self.label(label, parent)
        variable = tk.StringVar(value=str(value))
        if choices is not None:
            widget = ttk.Combobox(parent, textvariable=variable, values=choices, state="readonly")
        else:
            widget = ttk.Entry(parent, textvariable=variable, show="*" if masked else "")
        widget.pack(fill="x", pady=(0, 6))
        return variable, widget

    def check(self, label, value=False, parent=None, command=None):
        variable = tk.BooleanVar(value=value)
        ttk.Checkbutton(parent or self.page, text=label, variable=variable, command=command).pack(anchor="w", pady=5)
        return variable

    def show_step(self, number):
        self.reviewed = None
        self.selected_day = None
        self.step = number
        self.visited.add(number)
        self.clear(STEPS[number], SUBTITLES[number])
        getattr(self, f"step_{number}")()
        self.build_footer("Finish" if number == 7 and self.saved else "Save settings" if number == 7 else
                          "Check key" if number == 3 and not self.session.http else "Continue",
                          self.primary, self.back if number else None)
        if number == 1:
            self.check_aw()
        if number == 0 and not self.zone_initialized:
            self.zone_initialized = True
            def detect():
                try:
                    return setup.detected_timezone()
                except OSError:
                    return None
            self.work(detect, self.set_detected_zone)

    def primary(self):
        if self.step == 3 and not self.session.http:
            self.check_key()
        elif self.step == 7 and not self.saved:
            self.save()
        else:
            self.next()

    def step_0(self):
        self.label("autohours turns your local ActivityWatch activity into timesheets for your projects. "
                   "Review the time, then choose when to write it to Clockify or a spreadsheet.")
        self.label("Privacy: window titles never leave your computer. Only fixed descriptions and approved times go to your destination.")
        self.label("Your time zone", style="Heading.TLabel")
        self.zone_summary = self.label("")
        self.zone_picker = ttk.Frame(self.page)
        self.zone_picker.pack(fill="x")
        self.zone, self.zone_box = self.entry("Choose the city whose clock you use", self.session.raw["timezone"],
                                             parent=self.zone_picker, choices=sorted(available_timezones()))
        self.zone.trace_add("write", lambda *_: self.update_zone_summary())
        self.update_zone_summary()
        self.zone_change = self.button("Change", self.change_zone)
        if self.detected_zone == self.zone.get():
            self.zone_picker.pack_forget()

    def update_zone_summary(self):
        value = self.zone.get()
        city = value.rsplit("/", 1)[-1].replace("_", " ")
        self.zone_summary.configure(text=f"{city} ({value})" + (", detected" if value == self.detected_zone else ""))

    def set_detected_zone(self, value):
        if value and self.step == 0:
            self.detected_zone = value
            self.zone.set(value)
            self.zone_picker.pack_forget()

    def change_zone(self):
        self.zone_picker.pack(fill="x", before=self.zone_change)
        self.zone_box.focus_set()

    def step_1(self):
        self.label("Open ActivityWatch and let its window and AFK watchers record your apps and away time. "
                   "The check also confirms there is activity in the last seven days.")
        self.aw_label = self.label("✓ Window and away time are available." if self.aw_ready else "! Not checked yet.",
                                   style="Success.TLabel" if self.aw_ready else "Warning.TLabel")
        self.button("Download ActivityWatch", lambda: webbrowser.open("https://activitywatch.net/downloads/"))
        self.host, self.host_box = self.entry("Computer to use", self.session.raw["activitywatch"].get("hostname", ""), choices=[])
        self.web = self.check("Include website domains from my ActivityWatch browser extension",
                              self.session.raw["activitywatch"].get("use_web", False))
        self.button("Check again", self.check_aw)

    def check_aw(self):
        self.aw_ready = False
        self.aw_label.configure(text="Checking ActivityWatch...", style="Warning.TLabel")
        self.session.raw["activitywatch"]["use_web"] = self.web.get()
        def found(hosts):
            self.host_box.configure(values=hosts)
            if len(hosts) == 1:
                self.host.set(hosts[0])
            if self.host.get() not in hosts:
                self.aw_label.configure(text="! Select your computer, then click Check again.", style="Warning.TLabel")
                return
            self.session.raw["activitywatch"]["hostname"] = self.host.get()
            self.work(self.session.check_activity, checked)
        def checked(message):
            self.aw_ready = True
            self.aw_label.configure(text="✓ Checked: " + message, style="Success.TLabel")
        self.work(self.session.hosts, found)

    def step_2(self):
        self.destination = tk.StringVar(value=self.session.raw["destination"]["type"])
        self.destination.trace_add("write", lambda *_: self.render_sidebar())
        self.render_sidebar()
        for label, value in (("Clockify", "clockify"), ("Spreadsheet (CSV)", "csv")):
            ttk.Radiobutton(self.page, text=label, variable=self.destination, value=value).pack(anchor="w", pady=5)
        self.csv, _ = self.entry("Spreadsheet file", self.session.raw["destination"].get("path", ""))
        def pick():
            path = filedialog.asksaveasfilename(parent=self.root, title="Choose spreadsheet file",
                       defaultextension=".csv", filetypes=[("Spreadsheet CSV", "*.csv")])
            if path:
                self.csv.set(path)
                self.destination.set("csv")
        self.button("Choose file...", pick)

    def step_3(self):
        self.label("Open Clockify settings, find API and choose Generate. Paste the key here. "
                   "It stays masked and is saved privately when you save setup.")
        self.button("Open Clockify settings", lambda: webbrowser.open("https://app.clockify.me/user/preferences#advanced"))
        self.secret, _ = self.entry("Clockify API key (leave blank to use a saved key)", masked=True)
        self.key_label = self.label("✓ Key checked." if self.session.http else "! Not checked yet.",
                                    style="Success.TLabel" if self.session.http else "Warning.TLabel")
        self.button("Check key again", self.check_key)

    def check_key(self):
        candidate = self.secret.get()
        self.secret.set("")
        self.session.http = None
        self.key_label.configure(text="! Checking key...", style="Warning.TLabel")
        def checked(_):
            self.key_label.configure(text="✓ Key checked. It will not be shown again.", style="Success.TLabel")
            self.default.configure(text="Continue")
        self.work(lambda: self.session.check_key(candidate), checked)

    def step_4(self):
        labels = [s["name"] + " (" + s["id"] + ")" for s in self.session.spaces]
        self.workspace, self.workspace_box = self.entry("Clockify workspace", labels[0] if labels else "", choices=labels)

    def step_5(self):
        self.label("Private local activity from the last seven days. Select a project on the right, then tick its items. "
                   "An app includes all use of that app. If something matches two projects, the one higher "
                   "in the list wins. Use Move up to change the order.")
        if not self.session.raw["projects"]:
            self.button("Add your first project", self.add_project, style="Primary.TButton")
        self.coverage_label = self.label("Calculating your assigned time over the last 7 days...", style="Helper.TLabel")
        self.coverage_bar = ttk.Progressbar(self.page, maximum=100)
        self.coverage_bar.pack(fill="x", pady=(4, 16))
        columns = ttk.Frame(self.page)
        columns.pack(fill="both", expand=True)
        columns.columnconfigure(0, weight=3, uniform="projects")
        columns.columnconfigure(1, weight=2, uniform="projects")
        items = ttk.Frame(columns, padding=(0, 0, 14, 0))
        items.grid(row=0, column=0, sticky="nsew")
        self.search, _ = self.entry("Search apps, sites and titles", parent=items)
        self.search.trace_add("write", lambda *_: self.render_items())
        self.item_panel = ttk.Frame(items)
        self.item_panel.pack(fill="both", expand=True)
        right = ttk.Frame(columns)
        right.grid(row=0, column=1, sticky="nsew")
        self.label("Your projects", right)
        self.projects = ttk.Treeview(right, show="tree", height=8, selectmode="browse")
        self.projects.column("#0", width=self.px(150), minwidth=self.px(100))
        theme.stripe(self.projects, self.colors)
        self.projects.pack(fill="x")
        for i, row in enumerate(self.session.raw["projects"]):
            self.projects.insert("", "end", iid=str(i), text=row["name"], tags=("odd" if i % 2 else "even",))
        self.projects.bind("<<TreeviewSelect>>", lambda _: self.render_items())
        self.button("Add project", self.add_project, right)
        self.button("Move up", self.move_project, right)
        self.button("Edit description", self.edit_description, right)
        self.button("Remove project", self.remove_project, right)
        self.button("Refresh activity", lambda: self.work(self.session.check_activity, lambda _: self.show_step(5)), right)
        if self.session.raw["projects"]:
            self.projects.selection_set("0")
        self.render_items()
        self.root.after_idle(lambda: self.update_coverage() if self.step == 5 and not self.busy else None)

    def update_coverage(self):
        def shown(value):
            self.coverage_label.configure(text=f"{value:.0f}% of your last 7 days is assigned")
            self.coverage_bar.configure(value=value)
        self.work(self.session.coverage, shown)

    def project_index(self):
        selected = self.projects.selection()
        if not selected:
            raise UserError("Select a project first.")
        return int(selected[0])

    def render_items(self, focus_item=None):
        for widget in self.item_panel.winfo_children():
            widget.destroy()
        index = self.project_index() if self.projects.selection() else None
        row = self.session.raw["projects"][index] if index is not None else {}
        self.label("Activity items (tick to assign)" if index is not None else
                   "Recorded activity (add a project to assign items)", self.item_panel)
        query = self.search.get().strip().casefold()
        count = 0
        for i, ((kind, text), minutes) in enumerate(self.session.items):
            if query and query not in f"{kind} {text}".casefold():
                continue
            count += 1
            variable = tk.BooleanVar(value=setup.item_rule(kind, text) in row.get(kind, []))
            def changed(i=i, variable=variable):
                self.session.assign(index, i, variable.get())
                self.saved = False
                self.render_items(i)
                self.update_coverage()
            item = ttk.Frame(self.item_panel, padding=(0, 5))
            item.pack(fill="x")
            short = text if len(text) <= 34 else text[:31] + "..."
            widget = ttk.Checkbutton(item, text=f"{kind}: {short}",
                                      variable=variable, command=changed)
            widget.variable = variable
            if index is None:
                widget.state(["disabled"])
            widget.pack(anchor="w", fill="x")
            if focus_item == i:
                widget.focus_set()
            detail = ttk.Frame(item)
            detail.pack(fill="x", padx=(6, 0))
            ttk.Label(detail, text=f"{minutes / 60:.1f} h", style="Helper.TLabel").pack(side="right")
            owners = [p["name"] for p in self.session.raw["projects"] if setup.item_rule(kind, text) in p.get(kind, [])]
            if owners:
                self.label(", ".join(owners), detail, "Tag.TLabel")
        if not count:
            self.label("No activity matches your search." if query else "No activity items yet.", self.item_panel, "Helper.TLabel")
        if index is None:
            return
        self.label("Existing rules", self.item_panel)
        for kind in ("app", "url", "title"):
            for rule in row.get(kind, []):
                if any(setup.item_rule(k, t) == rule and k == kind for (k, t), _ in self.session.items):
                    continue
                def remove(kind=kind, rule=rule):
                    row[kind].remove(rule)
                    self.saved = False
                    self.show_step(5)
                rule_row = ttk.Frame(self.item_panel, padding=(0, 6))
                rule_row.pack(fill="x")
                self.label(f"{kind}: {rule}", rule_row, "Helper.TLabel")
                self.button("Remove rule", remove, rule_row)

    def dialog(self, title):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.bind("<Escape>", lambda _: dialog.destroy())
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        dialog.minsize(450, 180)
        return dialog, frame

    def add_project(self):
        dialog, frame = self.dialog("Add project")
        name, name_widget = self.entry("Project name", parent=frame)
        description, _ = self.entry("Timesheet description (no private titles)", parent=frame)
        options = [p["name"] + " (" + p["id"] + ")" for p in self.session.remote] + ["Create new"]
        remote = None
        if self.session.raw["destination"]["type"] == "clockify":
            _, remote = self.entry("Clockify project", options[0], frame, choices=options)
            self.label("New Clockify projects are created on Save and are visible to workspace members.", frame)
        def add():
            try:
                choice = remote.current() if remote else -1
                create = remote is not None and choice == len(self.session.remote)
                target = self.session.remote[choice]["id"] if remote and not create else None
                self.session.add_project(name.get(), description.get() or name.get(), target, create)
            except (UserError, ValueError) as exc:
                self.error(exc)
                return
            self.saved = False
            dialog.destroy()
            self.show_step(5)
            self.projects.selection_set(str(len(self.session.raw["projects"]) - 1))
        self.button("Add", add, frame)
        self.button("Cancel", dialog.destroy, frame)
        dialog.bind("<Return>", lambda _: add())
        name_widget.focus_set()

    def move_project(self):
        index = self.project_index()
        if index:
            rows = self.session.raw["projects"]
            rows[index - 1], rows[index] = rows[index], rows[index - 1]
            self.saved = False
            self.show_step(5)
            self.projects.selection_set(str(index - 1))

    def remove_project(self):
        index = self.project_index()
        name = self.session.raw["projects"][index]["name"]
        if messagebox.askyesno("Remove project", f"Remove {name} from these settings? Existing timesheets stay in place.", parent=self.root):
            del self.session.raw["projects"][index]
            self.session.pending = [n for n in self.session.pending if n != name]
            self.saved = False
            self.show_step(5)

    def edit_description(self):
        row = self.session.raw["projects"][self.project_index()]
        dialog, frame = self.dialog("Edit description")
        value, widget = self.entry("Timesheet description (no private titles)", row.get("description", row["name"]), frame)
        def save():
            row["description"] = setup.nonempty(value.get().strip())
            self.saved = False
            dialog.destroy()
        self.button("Save description", save, frame)
        dialog.bind("<Return>", lambda _: save())
        widget.focus_set()

    def step_6(self):
        self.agreement_fields = []
        self.page.configure(style="Page.TFrame", padding=0)
        for row in self.session.raw["projects"]:
            group = self.card(title=row["name"])
            old = {**self.session.raw.get("policy", {}), **row.get("agreement", {}),
                   **self.agreement_drafts.get(row["name"], {})}
            values = {}
            quantum = old.get("round_to_minutes", self.session.raw.get("blocks", {}).get("round_to_minutes", 0))
            quantum = "none" if str(quantum) == "0" else str(quantum)
            fields = (
                ("Billing type", "billing", old.get("billing", ""), ["hourly", "flat", "retainer", "none"],
                 "Choose none for non-billable work. Rate and currency are never assumed."),
                ("Rate (optional)", "rate", old.get("rate", ""), None, "Your agreed rate, used with the billing type."),
                ("Currency (optional)", "currency", old.get("currency", ""), None, "Use a three-letter code, such as CAD."),
                ("Count breaks up to (minutes)", "count_breaks_up_to_minutes", old.get("count_breaks_up_to_minutes", 0), None,
                 "Includes exactly this limit. Longer gaps stay excluded."),
                ("Calls while away", "count_calls_when_away", old.get("count_calls_when_away", False), None,
                 "Only matching projects, recognized calls and recorded away time count."),
                ("Round duration (minutes)", "round_to_minutes", quantum, list(dict.fromkeys(["none", "6", "15", "30", quantum])),
                 "Rounds each entry's duration. None keeps the original minutes."),
                ("Rounding method", "rounding", old.get("rounding", "nearest"), ["nearest", "up"],
                 "Choose the nearest interval or always round up."),
                ("Monthly cap (hours, optional)", "monthly_cap_hours", old.get("monthly_cap_hours", ""), None,
                 "Time above the cap is held back. Leave blank for no cap."))
            grid = ttk.Frame(group)
            grid.pack(fill="x")
            grid.columnconfigure((0, 1), weight=1, uniform="agreement")
            for index, (label, field, value, choices, helper) in enumerate(fields):
                cell = ttk.Frame(grid, padding=(0, 8, 12 if index % 2 == 0 else 0, 8))
                cell.grid(row=index // 2, column=index % 2, sticky="nsew")
                if field == "count_calls_when_away":
                    self.label(label, cell)
                    values[field] = self.check("Count calls while away", value, cell)
                else:
                    values[field], _ = self.entry(label, value, cell, choices=choices)
                self.label(helper, cell, "Helper.TLabel")
            self.agreement_fields.append((row, values))

    def collect_agreements(self):
        self.keep_agreement_drafts()
        pending = [(row, agreement({key: value.get() for key, value in values.items()}, row.get("agreement")))
                   for row, values in self.agreement_fields]
        for row, value in pending:
            row["agreement"] = value
        self.saved = False

    def keep_agreement_drafts(self):
        for row, values in self.agreement_fields:
            self.agreement_drafts[row["name"]] = {key: value.get() for key, value in values.items()}

    def step_7(self):
        cfg = self.session.config()
        self.label(f"Settings: {cfg.path}\nTime zone: {cfg.timezone}\nDestination: {cfg.destination.get('workspace', cfg.destination.get('path'))}")
        for row in cfg.projects:
            self.label(setup.agreement_summary(row, cfg.blocks))
        if self.session.pending:
            self.label("Create Clockify projects on Save (visible to workspace members): " + ", ".join(self.session.pending))
        self.label("Merging groups entries; excluded gaps are not billed. Duration rounding and short-block limits can change totals. "
                   "Unmatched time stays unbilled; accepted time can count. Existing entries are skipped. Sync checks destination caps too.")
        self.button("Save settings", self.save)
        self.doctor_label = self.label("! Save to check your settings.", style="Warning.TLabel")
        self.rates_label = self.label("Clockify rate differences: save first, then check rates." if cfg.destination["type"] == "clockify" else "Spreadsheet selected. Clockify rates do not apply.")
        self.button("Check rates differences", self.rates)
        self.button("Apply to Clockify", lambda: self.rates(apply=True))
        self.button("Review yesterday", lambda: self.load_review(self.yesterday()))
        self.review_panel = ttk.Frame(self.page)
        self.review_panel.pack(fill="both", expand=True)
        self.button("Write yesterday to " + ("Clockify" if cfg.destination["type"] == "clockify" else "spreadsheet"),
                    lambda: self.write_day(self.yesterday()))
        self.nightly = self.check("Run every night at the time below (automatically writes yesterday)")
        self.at, _ = self.entry("Nightly run time, on this computer (24-hour clock; 06:00 is 6:00 AM)", "06:00")
        self.label("Save and review first. Finish will show the exact schedule and ask for separate approval.")
        self.root.after_idle(lambda: self.load_review(self.yesterday()) if self.step == 7 and not self.busy else None)

    def save(self):
        self.reviewed = None
        self.selected_day = None
        def done(_):
            self.saved = True
            self.default.configure(text="Finish")
            self.status.set("Settings saved.")
            def checks():
                doctor = self.session.doctor()
                rates = self.session.rates()
                review = self.session.review(self.yesterday())
                return doctor, rates, review
            def checked(value):
                doctor, rates, review = value
                self.doctor_label.configure(text="✓ Settings checked. " + doctor.strip(), style="Success.TLabel")
                messages = rates[0]
                self.rates_label.configure(text=messages if isinstance(messages, str) else "\n".join(messages))
                self.reviewed = review
                self.selected_day = self.yesterday()
                self.render_review(self.selected_day, *review)
                self.status.set("Saved. Settings checked; review the time and rate differences below.")
            self.work(checks, checked)
        self.work(self.session.save, done)

    def rates(self, apply=False):
        if not self.saved:
            raise UserError("Save settings first, then check the exact Clockify differences.")
        if self.session.raw["destination"]["type"] != "clockify":
            self.show_text("Rates", "Spreadsheet selected. Clockify rates do not apply.")
            return
        def shown(result):
            messages, failed = result
            text = messages if isinstance(messages, str) else "\n".join(messages)
            if self.step == 7:
                self.rates_label.configure(text=text)
            self.show_text("Clockify rates", text, (lambda: self.work(lambda: self.session.rates(True),
                lambda result: self.show_text("Clockify readback", "\n".join(result[0]) +
                                              ("\nNeeds attention: some updates were refused or did not match." if result[1] else "")))) if apply else None)
        self.work(self.session.rates, shown)

    def show_text(self, title, text, approve=None):
        dialog, frame = self.dialog(title)
        self.label(title, frame)
        body = tk.Text(frame, width=75, height=18, wrap="word", font="TkDefaultFont", **theme.text_options(self.colors))
        bar = ttk.Scrollbar(frame, command=body.yview)
        bar.pack(side="right", fill="y")
        body.configure(yscrollcommand=bar.set)
        body.insert("1.0", text)
        body.configure(state="disabled")
        body.pack(fill="both", expand=True)
        if approve:
            def confirm():
                dialog.destroy()
                approve()
            self.button("Confirm these exact changes", confirm, frame)
        self.button("Close", dialog.destroy, frame)

    def yesterday(self):
        zone = ZoneInfo(self.session.raw["timezone"])
        return str(datetime.now(zone).date() - timedelta(days=1))

    def load_review(self, day):
        day = self.valid_day(day)
        self.reviewed = None
        self.selected_day = None
        def done(value):
            self.reviewed = value
            self.selected_day = day
            self.render_review(day, *value)
        self.work(lambda: self.session.review(day), done)

    @staticmethod
    def valid_day(day):
        try:
            if len(day) != 10:
                raise ValueError
            return str(date.fromisoformat(day))
        except ValueError:
            raise UserError("Choose a date in YYYY-MM-DD format, or use Yesterday or Today.") from None

    def render_review(self, day, cfg, result):
        for child in self.review_panel.winfo_children():
            child.destroy()
        summary = self.card(self.review_panel, f"Review for {day}")
        numbers = ttk.Frame(summary)
        numbers.pack(fill="x", pady=8)
        amounts = defaultdict(Decimal)
        for index, project in enumerate(cfg.projects):
            policy = project.agreement or {}
            if policy.get("billing") == "hourly" and "rate" in policy and "currency" in policy:
                minutes = sum(row.billed for row in result.reviews if row.project == index)
                amounts[policy["currency"]] += Decimal(str(minutes)) * Decimal(str(policy["rate"])) / 60
        metrics = [(f"{sum(block.minutes for block in result.blocks) / 60:.2f}", "Hours billed"),
                   (str(len(result.blocks)), "Entries to write")]
        metrics.extend((f"{amount:.2f} {currency}", "Hourly amount") for currency, amount in sorted(amounts.items()))
        for index, (value, label) in enumerate(metrics):
            cell = ttk.Frame(numbers, padding=(0, 4, 16, 4))
            cell.grid(row=index // 2, column=index % 2, sticky="nw")
            numbers.columnconfigure(index % 2, weight=1)
            self.label(value, cell, "Number.TLabel")
            self.label(label, cell, "Helper.TLabel")
        self.label("Local estimate. The write preview checks existing entries and destination caps before you confirm.",
                   summary, "Helper.TLabel")
        columns = ("project", "span", "worked", "billed", "reason")
        table = ttk.Treeview(self.review_panel, columns=columns, show="headings", height=7)
        theme.stripe(table, self.colors)
        for column, label, width in zip(columns, ("Project", "Activity span", "Worked min", "Billed min", "Explanation"), (160, 170, 95, 95, 420)):
            table.heading(column, text=label)
            table.column(column, width=self.px(width), minwidth=self.px(min(width, 220)))
        table.pack(fill="both", expand=True)
        horizontal = ttk.Scrollbar(self.review_panel, orient="horizontal", command=table.xview)
        horizontal.pack(fill="x")
        table.configure(xscrollcommand=horizontal.set)
        for index, row in enumerate(result.reviews):
            worked = sum(s.minutes for s in row.segments if s.kind == "worked")
            table.insert("", "end", tags=("odd" if index % 2 else "even",), values=(cfg.projects[row.project].name, span(row.start, row.end, cfg.timezone),
                                            f"{worked:.1f}", f"{row.billed:.1f}", reasons(row)))
        self.label(f"Unmatched: {sum(result.unmatched.values()):.1f} minutes. Filtered: {result.discarded_minutes:.1f} minutes.", self.review_panel)
        self.button("Show review details and totals", lambda: self.show_text("Review", text_review(result, cfg.projects, cfg.timezone)), self.review_panel)
        self.button("Open full report", lambda: self.work(lambda: full_report(cfg, result),
                    lambda path: webbrowser.open(path.as_uri())), self.review_panel)

    def write_day(self, day):
        day = self.valid_day(day)
        if not self.saved:
            raise UserError("Save settings and review the day before writing.")
        if self.selected_day != day or self.reviewed is None:
            raise UserError("Review this day first, then choose Write this day.")
        target = self.session.config().destination
        label = target.get("workspace", target.get("path"))
        def preview(text):
            self.show_text(f"Write {day} to {label}?", text + "\nConfirm to write this day only.",
                lambda: self.work(lambda: self.session.command("sync", day, "--write"), finished))
        def finished(text):
            self.reviewed = None
            self.selected_day = None
            self.show_text("Write result", text)
        self.work(lambda: self.session.command("sync", day), preview)

    def show_home(self):
        self.step = None
        self.home_view = 0
        self.clear("Your timesheets", "Review your work, keep projects up to date and choose when to write.")
        self.page.configure(style="Page.TFrame", padding=0)
        last = self.card(title="Last night")
        self.log_label = self.label("Checking the latest run...", last)
        tiles = ttk.Frame(self.page, style="Page.TFrame")
        tiles.pack(fill="x")
        tiles.columnconfigure((0, 1), weight=1, uniform="tiles")
        actions = (("Review a day", self.focus_review), ("Write a day", lambda: self.focus_review(write=True)),
                   ("Projects and rules", self.edit_projects), ("Nightly run\nChecking...", self.focus_nightly))
        for index, (label, action) in enumerate(actions):
            tile = ttk.Button(tiles, text=label, command=action, style="Tile.TButton")
            tile.grid(row=index // 2, column=index % 2, sticky="nsew", padx=(0, 12) if index % 2 == 0 else 0, pady=(0, 12))
            if index == 3:
                self.nightly_tile = tile
        self.build_footer("Review a day", self.focus_review)
        def status():
            return last_result(), nightly_status()
        def show(value):
            self.log_label.configure(text="Not run yet" if value[0] == "No run recorded yet." else value[0])
            self.nightly_tile.configure(text="Nightly run\n" + value[1])
        self.work(status, show)

    def focus_review(self, write=False):
        self.step = None
        self.home_view = 1
        self.reviewed = None
        self.selected_day = None
        self.clear("Review a day", "Review the day first, then preview and confirm any entries you want to write.")
        self.day, self.day_box = self.entry("Date (YYYY-MM-DD)", self.yesterday())
        shortcuts = ttk.Frame(self.page)
        shortcuts.pack(fill="x")
        self.button("Yesterday", lambda: self.day.set(self.yesterday()), shortcuts).pack(side="left", padx=(0, 8))
        self.button("Today", lambda: self.day.set(str(datetime.now(ZoneInfo(self.session.raw["timezone"])).date())), shortcuts).pack(side="left")
        self.review_panel = ttk.Frame(self.page)
        self.review_panel.pack(fill="both", expand=True, pady=(12, 0))
        self.button("Write this day", lambda: self.write_day(self.day.get()))
        self.build_footer("Review a day", lambda: self.load_review(self.day.get()), self.show_home)
        self.day_box.focus_set()
        if write:
            self.status.set("Choose a date and review it before writing.")

    def edit_projects(self):
        self.work(self.session.load_projects, lambda _: self.show_step(5))

    def focus_nightly(self):
        self.step = None
        self.home_view = 3
        self.clear("Nightly run", "Write yesterday automatically at an agreed time on this computer.")
        self.schedule_label = self.label("Checking the schedule...", style="Helper.TLabel")
        self.home_at, _ = self.entry("Time (24-hour clock; 06:00 is 6:00 AM)", "06:00")
        self.label("You will see the exact schedule before approving automatic writes. Missed days are not backfilled.", style="Helper.TLabel")
        self.button("Turn nightly run off", self.remove_schedule)
        self.build_footer("Preview schedule", lambda: self.offer_schedule(self.home_at.get()), self.show_home)
        self.work(nightly_status, lambda value: self.schedule_label.configure(text="Nightly run: " + value))

    def settings(self):
        self.work(lambda: open_settings(self.session.path), lambda _: None)

    def offer_schedule(self, at, finished=None):
        if not self.saved:
            raise UserError("Save settings before enabling nightly runs.")
        def plan():
            self.session.require_saved()
            self.session.doctor()
            cron = schedule.read_crontab() if sys.platform not in ("win32", "darwin") else ""
            return schedule.build_plan(self.session.path, at, crontab=cron)
        def preview(value):
            self.show_text("Allow automatic nightly writes?", value.describe() +
                "\nThis writes yesterday only, using your computer's clock. Missed days are not backfilled.",
                lambda: self.work(lambda: schedule.install(value), lambda _: (finished or self.show_home)()))
        self.work(plan, preview)

    def remove_schedule(self):
        if messagebox.askyesno("Stop nightly runs", "Remove autohours' nightly schedule?", parent=self.root):
            self.work(schedule.remove, lambda _: self.show_home())

    def next(self):
        if self.busy:
            return
        number = self.step
        if number == 0:
            ZoneInfo(self.zone.get())
            self.session.raw["timezone"] = self.zone.get()
        elif number == 1:
            if not self.aw_ready or self.host.get() != self.session.raw["activitywatch"].get("hostname") or self.web.get() != self.session.raw["activitywatch"].get("use_web", False):
                raise UserError("Click Check again to verify this computer's window and away time first.")
        elif number == 2:
            if self.destination.get() == "csv":
                path = Path(self.csv.get()).expanduser()
                if not self.csv.get() or not path.parent.is_dir() or path.is_dir():
                    raise UserError("Choose a spreadsheet filename in an existing folder.")
                self.session.raw["destination"] = {"type": "csv", "path": str(path.resolve())}
                self.show_step(5)
                return
            if self.session.raw["destination"]["type"] != "clockify":
                if self.session.raw["projects"]:
                    raise UserError("Remove existing spreadsheet projects before switching to Clockify, then add projects for its workspace.")
                self.session.raw["destination"] = {"type": "clockify"}
        elif number == 3:
            if not self.session.http:
                raise UserError("Check the key first.")
            self.secret.set("")
        elif number == 4:
            index = self.workspace_box.current()
            if index < 0:
                raise UserError("Choose a workspace.")
            self.work(lambda: self.session.choose_workspace(index), lambda _: self.show_step(5))
            return
        elif number == 5:
            self.session.config()
        elif number == 6:
            self.collect_agreements()
            self.session.config()
        elif number == 7:
            if not self.saved:
                raise UserError("Click Save before finishing.")
            if self.nightly.get():
                self.offer_schedule(self.at.get(), self.show_home)
            else:
                self.show_home()
            return
        self.show_step(number + 1)

    def back(self):
        if self.busy:
            return
        if self.step == 3:
            self.secret.set("")
        if self.step == 6:
            self.keep_agreement_drafts()
        if self.step == 5:
            if self.session.original:
                self.cancel()
                return
            self.show_step(2 if self.session.raw["destination"]["type"] == "csv" else 4)
        elif self.step:
            self.show_step(self.step - 1)

    def cancel(self):
        if self.busy:
            messagebox.showinfo("Working", "Wait for this operation to finish before closing. A write may already be in progress.", parent=self.root)
            return
        if self.step is not None and not messagebox.askyesno("Cancel setup", "Discard unsaved changes? Saved settings and completed writes remain.", parent=self.root):
            return
        if self.step is not None and self.session.original:
            self.session = Session(self.session.path)
            self.agreement_drafts = {}
            self.saved = True
            self.show_home()
        else:
            self.root.destroy()


def launch(explicit=None):
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    try:
        root = tk.Tk()
    except tk.TclError:
        raise UserError("The desktop app needs a graphical display and Python with Tk support.") from None
    try:
        App(root, Session(explicit))
        root.mainloop()
    except (UserError, OSError, ValueError) as exc:
        messagebox.showerror("Could not open settings", str(exc), parent=root)
        root.destroy()
        return 1
    return 0
