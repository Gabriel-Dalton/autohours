"""A small ttk front end. Workers never read or update Tk widgets."""

from datetime import date, datetime, timedelta
from pathlib import Path
from queue import Empty, Queue
import sys
from threading import Thread
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser
from zoneinfo import ZoneInfo, available_timezones

from . import schedule, setup
from .desktop import Session, agreement, full_report, open_settings
from .models import UserError
from .review import reasons, span, text_review
from .runlog import last_result


STEPS = ("Welcome", "ActivityWatch", "Where timesheets go", "Clockify key",
         "Workspace", "Projects and rules", "Project agreements", "Check and finish")


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
        self.root.title("autohours")
        self.root.geometry("1000x760")
        self.root.minsize(640, 480)
        style = ttk.Style(root)
        style.configure("TButton", padding=(10, 6))
        style.configure("TLabel", padding=(0, 3))
        style.configure("Treeview", rowheight=30)
        self.status = tk.StringVar(value="Ready")
        ttk.Label(root, textvariable=self.status).pack(side="bottom", fill="x", padx=16)
        self.footer = ttk.Frame(root, padding=12)
        self.footer.pack(side="bottom", fill="x")
        self.canvas = tk.Canvas(root, highlightthickness=0)
        scrollbar = ttk.Scrollbar(root, orient="vertical", command=self.canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.page = ttk.Frame(self.canvas, padding=20)
        self.page_id = self.canvas.create_window((0, 0), window=self.page, anchor="nw")
        self.page.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self.resize)
        root.bind("<FocusIn>", self.reveal_focus, add=True)
        root.bind("<Return>", self.enter)
        root.bind("<Escape>", lambda _: self.cancel())
        root.protocol("WM_DELETE_WINDOW", self.cancel)
        root.report_callback_exception = lambda *args: self.error(args[1])
        self.default = None
        self.show_home() if self.saved else self.show_step(0)

    def resize(self, event):
        self.canvas.itemconfigure(self.page_id, width=event.width)
        ttk.Style(self.root).configure("Activity.TCheckbutton", wraplength=max(220, int(event.width * 0.5)))

    def reveal_focus(self, event):
        widget = event.widget
        if str(widget).startswith(str(self.page)):
            self.root.update_idletasks()
            y = widget.winfo_rooty() - self.page.winfo_rooty()
            top = self.canvas.canvasy(0)
            if y < top or y + widget.winfo_height() > top + self.canvas.winfo_height():
                self.canvas.yview_moveto(max(0, y - 30) / max(1, self.page.winfo_height()))

    def enter(self, event):
        if self.busy or event.widget.winfo_toplevel() != self.root:
            return
        if isinstance(event.widget, ttk.Button):
            event.widget.invoke()
        elif self.default and not isinstance(event.widget, (tk.Text, ttk.Combobox)):
            self.default.invoke()
        return "break"

    def error(self, exc):
        message = str(exc) if isinstance(exc, (UserError, ValueError)) else (
            "That action could not finish. Check your connection and settings, then try again. "
            "Review the day again before retrying a write.")
        messagebox.showerror("Needs attention", message, parent=self.root)

    def work(self, callback, done):
        if self.busy:
            return
        self.busy = True
        self.status.set("Working...")
        states = []
        def disable(parent):
            for child in parent.winfo_children():
                if isinstance(child, ttk.Widget) and hasattr(child, "state"):
                    states.append((child, child.state()))
                    child.state(["disabled"])
                disable(child)
        disable(self.page)
        disable(self.footer)
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
            self.status.set("Ready" if ok else "Needs attention")
            for widget, previous in states:
                if widget.winfo_exists():
                    widget.state(["!disabled", *previous])
            if ok:
                done(value)
            else:
                self.error(value)
        self.root.after(75, poll)

    def clear(self, heading):
        for parent in (self.page, self.footer):
            for child in parent.winfo_children():
                child.destroy()
        self.default = None
        self.canvas.yview_moveto(0)
        ttk.Label(self.page, text=heading, font=("TkDefaultFont", 18, "bold")).pack(anchor="w", pady=(0, 12))

    def label(self, text, parent=None):
        label = ttk.Label(parent or self.page, text=text, wraplength=760, justify="left")
        label.pack(anchor="w", fill="x", pady=3)
        label.bind("<Configure>", lambda event: label.configure(wraplength=max(200, event.width - 10)))
        return label

    def button(self, text, action, parent=None):
        button = ttk.Button(parent or self.page, text=text, command=action)
        button.pack(anchor="w", pady=5)
        return button

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
        self.clear(f"Step {number + 1} of 8: {STEPS[number]}")
        getattr(self, f"step_{number}")()
        back = self.button("Back", self.back, self.footer)
        back.pack(side="left")
        if number == 0:
            back.state(["disabled"])
        self.button("Cancel", self.cancel, self.footer).pack(side="right")
        self.default = self.button("Finish" if number == 7 else "Next", self.next, self.footer)
        self.default.pack(side="right", padx=10)

    def step_0(self):
        self.label("autohours turns your local ActivityWatch activity into timesheets for your projects. "
                   "Review the time, then choose when to write it to Clockify or a spreadsheet.")
        self.label("Privacy: window titles never leave your computer. Only fixed descriptions and approved times go to your destination.")
        self.zone, _ = self.entry("Your time zone (choose the city whose clock you use)", self.session.raw["timezone"],
                                  choices=sorted(available_timezones()))
        self.button("Detect my time zone", lambda: self.work(setup.detected_timezone,
                    lambda value: self.zone.set(value or "UTC")))

    def step_1(self):
        self.label("Open ActivityWatch and let its window and AFK watchers record your apps and away time. "
                   "The check also confirms there is activity in the last seven days.")
        self.aw_label = self.label("Checked: window and away time are available." if self.aw_ready else "Not checked yet.")
        self.button("Download ActivityWatch", lambda: webbrowser.open("https://activitywatch.net/downloads/"))
        self.host, self.host_box = self.entry("Computer to use", self.session.raw["activitywatch"].get("hostname", ""), choices=[])
        self.web = self.check("Include website domains from my ActivityWatch browser extension",
                              self.session.raw["activitywatch"].get("use_web", False))
        self.button("Check again", self.check_aw)

    def check_aw(self):
        self.aw_ready = False
        self.session.raw["activitywatch"]["use_web"] = self.web.get()
        def found(hosts):
            self.host_box.configure(values=hosts)
            if len(hosts) == 1:
                self.host.set(hosts[0])
            if self.host.get() not in hosts:
                self.aw_label.configure(text="Select your computer, then click Check again.")
                return
            self.session.raw["activitywatch"]["hostname"] = self.host.get()
            self.work(self.session.check_activity, checked)
        def checked(message):
            self.aw_ready = True
            self.aw_label.configure(text="\u2713 Checked: " + message, foreground="#176327")
        self.work(self.session.hosts, found)

    def step_2(self):
        self.destination = tk.StringVar(value=self.session.raw["destination"]["type"])
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
        self.key_label = self.label("Key checked." if self.session.http else "Not checked yet.")
        def check():
            candidate = self.secret.get()
            self.secret.set("")
            self.session.http = None
            self.work(lambda: self.session.check_key(candidate), lambda _: self.key_label.configure(text="Key checked. It will not be shown again."))
        self.button("Check key", check)

    def step_4(self):
        labels = [s["name"] + " (" + s["id"] + ")" for s in self.session.spaces]
        self.workspace, self.workspace_box = self.entry("Clockify workspace", labels[0] if labels else "", choices=labels)

    def step_5(self):
        self.label("Private local activity from the last seven days. Select a project on the right, then tick its items. "
                   "An app includes all use of that app. Categories overlap; first matching project wins.")
        self.coverage_label = self.label("Your rules cover: calculating the last 7 days...")
        columns = ttk.Frame(self.page)
        columns.pack(fill="both", expand=True)
        columns.columnconfigure(0, weight=3)
        columns.columnconfigure(1, weight=2)
        self.item_panel = ttk.Frame(columns, padding=(0, 0, 14, 0))
        self.item_panel.grid(row=0, column=0, sticky="nsew")
        right = ttk.Frame(columns)
        right.grid(row=0, column=1, sticky="nsew")
        self.label("Projects (matching order)", right)
        self.projects = ttk.Treeview(right, show="tree", height=8, selectmode="browse")
        self.projects.column("#0", width=230, minwidth=140)
        self.projects.pack(fill="x")
        for i, row in enumerate(self.session.raw["projects"]):
            self.projects.insert("", "end", iid=str(i), text=row["name"])
        self.projects.bind("<<TreeviewSelect>>", lambda _: self.render_items())
        self.button("Add project", self.add_project, right)
        self.button("Move selected project up", self.move_project, right)
        self.button("Edit description", self.edit_description, right)
        self.button("Remove selected project", self.remove_project, right)
        self.button("Refresh local activity", lambda: self.work(self.session.check_activity, lambda _: self.show_step(5)), right)
        if self.session.raw["projects"]:
            self.projects.selection_set("0")
        self.render_items()
        self.root.after_idle(lambda: self.update_coverage() if self.step == 5 and not self.busy else None)

    def update_coverage(self):
        self.work(self.session.coverage, lambda value: self.coverage_label.configure(
            text=f"Your rules cover {value:.0f}% of the last 7 days."))

    def project_index(self):
        selected = self.projects.selection()
        if not selected:
            raise UserError("Select a project first.")
        return int(selected[0])

    def render_items(self):
        for widget in self.item_panel.winfo_children():
            widget.destroy()
        if not self.projects.selection():
            self.label("Add a project to start choosing its activity.", self.item_panel)
            return
        index = self.project_index()
        row = self.session.raw["projects"][index]
        self.label("Activity items (tick to assign)", self.item_panel)
        for i, ((kind, text), minutes) in enumerate(self.session.items):
            variable = tk.BooleanVar(value=setup.item_rule(kind, text) in row.get(kind, []))
            def changed(i=i, variable=variable):
                self.session.assign(index, i, variable.get())
                self.saved = False
                self.update_coverage()
            widget = ttk.Checkbutton(self.item_panel, text=f"{kind}: {text} ({minutes / 60:.1f} hours)", style="Activity.TCheckbutton",
                                      variable=variable, command=changed)
            widget.variable = variable
            widget.pack(anchor="w", pady=4)
        self.label("Existing rules", self.item_panel)
        for kind in ("app", "url", "title"):
            for rule in row.get(kind, []):
                if any(setup.item_rule(k, t) == rule and k == kind for (k, t), _ in self.session.items):
                    continue
                def remove(kind=kind, rule=rule):
                    row[kind].remove(rule)
                    self.saved = False
                    self.show_step(5)
                self.button(f"Remove {kind} rule: {rule[:65]}", remove, self.item_panel)

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
        self.label("Confirm each project's agreement. Rate and currency are optional; neither is assumed.")
        for row in self.session.raw["projects"]:
            group = ttk.LabelFrame(self.page, text=row["name"], padding=12)
            group.pack(fill="x", pady=10)
            old = {**self.session.raw.get("policy", {}), **row.get("agreement", {}),
                   **self.agreement_drafts.get(row["name"], {})}
            values = {}
            values["billing"] = tk.StringVar(value=old.get("billing", ""))
            self.label("Billing (choose one)", group)
            for label, value in (("Hourly", "hourly"), ("Flat monthly", "flat"), ("Retainer", "retainer"), ("Not billed", "none")):
                ttk.Radiobutton(group, text=label, variable=values["billing"], value=value).pack(anchor="w")
            for label, field in (("Rate (optional)", "rate"), ("Currency, three letters (optional)", "currency"),
                                 ("Short breaks count up to this many minutes (including exactly this limit)", "count_breaks_up_to_minutes")):
                values[field], _ = self.entry(label, old.get(field, 0 if field.endswith("minutes") else ""), group)
            values["count_calls_when_away"] = self.check("Count calls when I'm away from the keyboard", old.get("count_calls_when_away", False), group)
            self.label("Only calls with a matching project, recognized call app or title, and recorded away time count.", group)
            quantum = old.get("round_to_minutes", self.session.raw.get("blocks", {}).get("round_to_minutes", 0))
            quantum = "none" if str(quantum) == "0" else str(quantum)
            choices = list(dict.fromkeys(["none", "6", "15", "30", quantum]))
            values["round_to_minutes"], _ = self.entry("Round duration in minutes", quantum, group, choices=choices)
            values["rounding"], _ = self.entry("Rounding method", old.get("rounding", "nearest"), group, choices=["nearest", "up"])
            values["monthly_cap_hours"], _ = self.entry("Monthly cap in hours (optional)", old.get("monthly_cap_hours", ""), group)
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
        self.button("Save", self.save)
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
            self.status.set("Settings saved.")
            def checks():
                doctor = self.session.doctor()
                rates = self.session.rates()
                review = self.session.review(self.yesterday())
                return doctor, rates, review
            def checked(value):
                _, rates, review = value
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
        body = tk.Text(frame, width=85, height=22, wrap="word", font="TkDefaultFont")
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
        self.label(f"Review for {day}", self.review_panel)
        columns = ("project", "span", "worked", "billed", "reason")
        table = ttk.Treeview(self.review_panel, columns=columns, show="headings", height=7)
        for column, label, width in zip(columns, ("Project", "Activity span", "Worked min", "Billed min", "Explanation"), (160, 170, 95, 95, 420)):
            table.heading(column, text=label)
            table.column(column, width=width, minwidth=80)
        table.pack(fill="both", expand=True)
        horizontal = ttk.Scrollbar(self.review_panel, orient="horizontal", command=table.xview)
        horizontal.pack(fill="x")
        table.configure(xscrollcommand=horizontal.set)
        for row in result.reviews:
            worked = sum(s.minutes for s in row.segments if s.kind == "worked")
            table.insert("", "end", values=(cfg.projects[row.project].name, span(row.start, row.end, cfg.timezone),
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
        self.clear("Your timesheets")
        self.log_label = self.label("Last night's result: checking...")
        self.day, _ = self.entry("Review a day (YYYY-MM-DD)", self.yesterday())
        self.button("Yesterday", lambda: self.day.set(self.yesterday()))
        self.button("Today", lambda: self.day.set(str(datetime.now(ZoneInfo(self.session.raw["timezone"])).date())))
        self.default = self.button("Review a day", lambda: self.load_review(self.day.get()))
        self.review_panel = ttk.Frame(self.page)
        self.review_panel.pack(fill="both", expand=True)
        self.button("Write this day", lambda: self.write_day(self.day.get()))
        self.button("Edit projects and rules", lambda: self.work(self.session.load_projects, lambda _: self.show_step(5)))
        self.schedule_label = self.label("Nightly run: checking...")
        self.home_at, _ = self.entry("Nightly run time (24-hour clock; 06:00 is 6:00 AM)", "06:00")
        self.button("Turn nightly run on", lambda: self.offer_schedule(self.home_at.get()))
        self.button("Turn nightly run off", self.remove_schedule)
        self.button("Open settings file", lambda: self.work(lambda: open_settings(self.session.path), lambda _: None))
        def status():
            return last_result(), schedule.enabled()
        def show(value):
            self.log_label.configure(text="Last night's result: " + value[0])
            self.schedule_label.configure(text="Nightly run: " + ("on" if value[1] else "off"))
        self.work(status, show)

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
