import csv
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode

from .http import JsonHTTP
from .credentials import read_key
from .models import Block, UserError, iso, overlaps, timestamp


def resolve(items, wanted, kind):
    by_id = [item for item in items if item["id"] == wanted]
    matches = by_id or [item for item in items if item["name"] == wanted]
    if len(matches) == 1:
        return matches[0]["id"]
    available = ", ".join(f"{item['name']} ({item['id']})" for item in items) or "none"
    problem = "is ambiguous" if matches else "was not found"
    raise UserError(f"{kind} '{wanted}' {problem}. Available: {available}. Use the exact name or ID.")


class Clockify:
    def __init__(self, settings, projects, http=None):
        key = read_key() if http is None else ""
        if not key and http is None:
            raise UserError("Run autohours setup or set CLOCKIFY_API_KEY. Get it from Clockify Profile settings; never put it in the config.")
        self.http = http or JsonHTTP("https://api.clockify.me/api/v1", {"X-Api-Key": key}, "Clockify")
        self.settings = settings
        self.projects = projects
        self.workspace = None
        self.user = None
        self.project_ids = {}

    def _pages(self, path, params=None):
        result = []
        page = 1
        while True:
            rows = self.http.request("GET", path + "?" + urlencode({**(params or {}), "page": page, "page-size": 100}))
            if not isinstance(rows, list):
                raise UserError("Clockify returned an unexpected list response. Check its API version.")
            result.extend(rows)
            if len(rows) < 100:
                return result
            page += 1

    def check(self):
        self.user = quote(self.http.request("GET", "/user")["id"], safe="")
        workspaces = self.http.request("GET", "/workspaces")
        self.workspace = quote(resolve(workspaces, self.settings["workspace"], "Workspace"), safe="")
        projects = self._pages(f"/workspaces/{self.workspace}/projects", {"archived": "false"})
        self.project_ids = {p.destination_project: resolve(projects, p.destination_project, "Project") for p in self.projects}
        for p in self.projects:
            if "monthly_cap_hours" in (p.agreement or {}) or "billing" in (p.agreement or {}):
                identifier = self.project_ids[p.destination_project]
                if sum(self.project_ids[other.destination_project] == identifier for other in self.projects) > 1:
                    raise UserError("Projects with billing agreements or caps must resolve to distinct Clockify projects.")
        return "Clockify API key is valid; workspace and all projects found."

    def existing(self, start, end):
        if self.workspace is None:
            self.check()
        # No lower bound: entries can begin before the requested date and still overlap.
        rows = self._pages(f"/workspaces/{self.workspace}/user/{self.user}/time-entries", {"end": iso(end)})
        # Some API versions exclude running timers when a date filter is present.
        rows += self._pages(f"/workspaces/{self.workspace}/user/{self.user}/time-entries", {"in-progress": "true"})
        intervals = []
        for row in rows:
            interval = row["timeInterval"]
            a = timestamp(interval["start"])
            b = timestamp(interval["end"]) if interval.get("end") else datetime.max.replace(tzinfo=timezone.utc)
            if overlaps((a, b), (start, end)):
                intervals.append((a, b))
        return intervals

    def create(self, block):
        self.http.request("POST", f"/workspaces/{self.workspace}/time-entries", {
            "start": iso(block.start), "end": iso(block.end),
            "description": block.description, "billable": block.billable,
            "projectId": self.project_ids[block.project],
        })

    def logged(self, start, end):
        """Own entries, including manual time, for monthly cap accounting."""
        if self.workspace is None:
            self.check()
        rows = self._pages(f"/workspaces/{self.workspace}/user/{self.user}/time-entries", {"end": iso(end)})
        rows += self._pages(f"/workspaces/{self.workspace}/user/{self.user}/time-entries", {"in-progress": "true"})
        names = {identifier: name for name, identifier in self.project_ids.items()}
        blocks, seen = [], set()
        for row in rows:
            interval = row["timeInterval"]
            a = max(start, timestamp(interval["start"]))
            b = min(end, timestamp(interval["end"])) if interval.get("end") else end
            key = row.get("id", (row.get("projectId"), iso(a), iso(b)))
            if a < b and key not in seen and row.get("projectId") in names:
                blocks.append(Block(a, b, names[row["projectId"]], "", False))
                seen.add(key)
        return blocks


FORMULA_START = ("=", "+", "-", "@", chr(9), chr(13))


def cell(text):
    """Spreadsheets run text that starts like a formula; a leading apostrophe keeps it as text."""
    return "'" + text if text.startswith(FORMULA_START) else text


def uncell(text):
    return text[1:] if text.startswith("'") and text[1:].startswith(FORMULA_START) else text


class CSV:
    fields = ["date", "start", "end", "minutes", "project", "description", "billable"]

    def __init__(self, settings, zone):
        self.path = Path(settings["path"])
        self.zone = zone

    def check(self):
        if not self.path.parent.is_dir():
            raise UserError(f"CSV folder does not exist: {self.path.parent}. Create it or change destination.path.")
        if self.path.exists() and not self.path.is_file():
            raise UserError("CSV path must point to a file, not a folder.")
        self.existing(datetime.min.replace(tzinfo=timezone.utc), datetime.max.replace(tzinfo=timezone.utc))
        return f"CSV destination ready: {self.path}"

    def existing(self, start, end):
        if not self.path.exists() or self.path.stat().st_size == 0:
            return []
        intervals = []
        try:
            with self.path.open(newline="", encoding="utf-8-sig") as stream:
                reader = csv.DictReader(stream)
                if reader.fieldnames != self.fields:
                    raise ValueError("Wrong columns")
                for row in reader:
                    a, b = timestamp(row["start"]), timestamp(row["end"])
                    if b <= a:
                        raise ValueError("Invalid interval")
                    if overlaps((a, b), (start, end)):
                        intervals.append((a, b))
        except (ValueError, KeyError, TypeError, csv.Error):
            raise UserError("Existing CSV has invalid columns or times. Choose a new path or fix the file before syncing.") from None
        return intervals

    def create(self, block):
        header = not self.path.exists() or self.path.stat().st_size == 0
        # A byte order mark lets Excel read accented and non-Latin names correctly.
        with self.path.open("a", newline="", encoding="utf-8-sig" if header else "utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=self.fields)
            if header:
                writer.writeheader()
            writer.writerow({"date": block.start.astimezone(self.zone).date().isoformat(),
                             "start": block.start.astimezone(self.zone).isoformat(),
                             "end": block.end.astimezone(self.zone).isoformat(),
                             "minutes": f"{block.minutes:.2f}", "project": cell(block.project),
                             "description": cell(block.description), "billable": str(block.billable).lower()})

    def logged(self, start, end):
        self.existing(start, end)  # Validate before reading project totals.
        if not self.path.exists() or not self.path.stat().st_size:
            return []
        with self.path.open(newline="", encoding="utf-8-sig") as stream:
            result = []
            for row in csv.DictReader(stream):
                a, b = max(start, timestamp(row["start"])), min(end, timestamp(row["end"]))
                if a < b:
                    result.append(Block(a, b, uncell(row["project"]), "", False))
            return result


def sync(destination, blocks, start, end, write=False, summary=None):
    existing = destination.existing(start, end)
    created = skipped = 0
    minutes = 0
    for block in blocks:
        interval = block.start, block.end
        if any(overlaps(interval, old) for old in existing):
            skipped += 1
            continue
        if write:
            destination.create(block)
        existing.append(interval)
        created += 1
        minutes += block.minutes
    if summary is not None:
        summary.update(entries=created, skipped=skipped, hours=minutes / 60)
    return created, skipped
