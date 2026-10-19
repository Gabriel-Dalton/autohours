"""Local evidence stays separate from the destination payload."""

from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from html import escape

from .pipeline import agreement


LABELS = {"worked": "worked", "counted-break": "short breaks counted (policy)",
          "call": "calls counted while away", "accepted": "accepted",
          "excluded-away": "away gaps excluded", "unmatched": "unmatched",
          "interruption": "interruptions excluded"}


def safe(value):
    return "".join(c if c.isprintable() else " " for c in str(value))


def stamp(value, zone):
    local = value.astimezone(zone)
    text = local.strftime("%H:%M")
    # Preserve the offset only during a repeated hour, when HH:MM is ambiguous.
    if local.replace(fold=0).utcoffset() != local.replace(fold=1).utcoffset():
        offset = local.strftime("%z")
        text += f" ({offset[:3]}:{offset[3:]})"
    return text


def span(start, end, zone):
    a, b = start.astimezone(zone), end.astimezone(zone)
    suffix = f" ({b.date()})" if a.date() != b.date() else ""
    return f"{stamp(start, zone)} to {stamp(end, zone)}{suffix}"


def totals(result, projects):
    for index, project in enumerate(projects):
        minutes = sum(r.billed for r in result.reviews if r.project == index)
        policy = agreement(project)
        detail = policy.get("billing", "billable" if project.billable else "non-billable")
        if detail == "hourly":
            if "rate" not in policy:
                detail = "rate not set"
            elif "currency" not in policy:
                detail = "currency not set"
            else:
                rate = Decimal(str(policy["rate"]))
                amount = rate * Decimal(str(minutes)) / 60
                detail = f"{rate} {policy['currency']} x {minutes / 60:.2f} hours = {amount:.2f} {policy['currency']}"
        yield project.name, minutes, detail


def reasons(row):
    values = defaultdict(float)
    for s in row.segments:
        values[s.kind] += s.minutes
    parts = [f"{LABELS[kind]}: {minutes:.1f} min" for kind, minutes in values.items()]
    if row.rounding:
        parts.append(f"rounding {'added' if row.rounding > 0 else 'removed'}: {abs(row.rounding):.1f} min")
    if row.held:
        parts.append(f"monthly cap exceeded; held back by cap: {row.held:.1f} min")
    if row.filtered:
        parts.append("short block filtered out")
    return "; ".join(parts)


def summary_lines(result, projects, titles=False):
    for index, project in enumerate(projects):
        rows = [r for r in result.reviews if r.project == index]
        filtered = sum(sum(s.minutes for s in r.segments
                           if s.kind in ("worked", "call", "accepted", "counted-break"))
                       if r.filtered else max(0, -r.rounding) for r in rows)
        held = sum(r.held for r in rows)
        detail = f"; monthly cap exceeded; held back by cap: {held:.1f} min" if held else ""
        yield f"{safe(project.name)}: filtered out {filtered:.1f} min{detail}"
    yield f"Unmatched: {sum(result.unmatched.values()):.1f} minutes (never written)"
    unmatched = Counter()
    for (app, title), minutes in result.unmatched.items():
        label = f"{app} | {title}" if titles else app or "Unknown app"
        unmatched[label] += minutes
    for label, minutes in unmatched.most_common(10):
        yield f"  {minutes:.1f} min  {safe(label)}"
    yield f"Filtered out: {result.discarded_minutes:.1f} minutes"
    for name, minutes, detail in totals(result, projects):
        yield f"{safe(name)}: {minutes:.1f} min; {detail}"
    yield f"Total billed: {sum(b.minutes for b in result.blocks):.1f} minutes"


def text_review(result, projects, zone, titles=False, verbose=False):
    lines = []
    day = None
    if not result.blocks:
        lines.append("No matching blocks. Check your rules, minimum block length and AFK watcher.")
    for row in result.reviews:
        if not verbose and row.billed <= 0:
            continue
        local_day = row.start.astimezone(zone).date()
        if local_day != day:
            lines.append(str(local_day))
            day = local_day
        worked = sum(s.minutes for s in row.segments if s.kind in ("worked", "call", "accepted"))
        lines.append(f"{span(row.start, row.end, zone)}  {safe(projects[row.project].name)}  worked {worked:.1f} min; billed {row.billed:.1f} min")
        lines.append("  " + reasons(row))
        if row.billed:
            entry_end = row.entry_start + timedelta(minutes=row.billed)
            lines.append(f"  Entry: {span(row.entry_start, entry_end, zone)}")
        if titles:
            lines.extend("  " + safe(title) for title in sorted({s.title for s in row.segments if s.title}))
    if verbose:
        lines.append("Activity detail:")
        day = None
        for s in timeline_segments(result):
            local_day = s.start.astimezone(zone).date()
            if local_day != day:
                lines.append(str(local_day))
                day = local_day
            name = projects[s.project].name if s.project is not None else "Unmatched"
            lines.append(f"  {span(s.start, s.end, zone)}  {safe(name)}: {LABELS[s.kind]}, {s.minutes:.1f} min")
            if titles and s.title:
                lines.append("  " + safe(s.title))
    lines.extend(summary_lines(result, projects, titles))
    return "\n".join(lines)


def timeline_segments(result):
    # Real evidence is disjoint, unlike merged project spans. Overlay only
    # counted breaks, so interruptions never hide another project's evidence.
    breaks = [s for row in result.reviews for s in row.segments if s.kind == "counted-break"]
    segments = list(breaks)
    for raw in result.segments:
        pieces = [raw]
        for row in breaks:
            remaining = []
            for s in pieces:
                if s.end <= row.start or s.start >= row.end:
                    remaining.append(s)
                else:
                    if s.start < row.start:
                        remaining.append(replace(s, end=row.start))
                    if s.end > row.end:
                        remaining.append(replace(s, start=row.end))
            pieces = remaining
        segments.extend(replace(s, kind="unmatched") if s.project is None and s.kind != "excluded-away" else s for s in pieces)
    return sorted(segments, key=lambda s: s.start)


REPORT_STYLE = """
:root{color-scheme:light dark;--bg:#fff;--layer:#f4f4f4;--text:#161616;--muted:#525252;--line:#c6c6c6;--track:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--layer:#262626;--text:#f4f4f4;--muted:#c6c6c6;--line:#525252;--track:#161616}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 "IBM Plex Sans",system-ui,sans-serif}
main{max-width:64rem;margin:auto;padding:2rem 1rem 4rem}h1{font-weight:400;font-size:2rem;margin:0 0 .25rem}
h2{font-weight:400;font-size:1.5rem;margin:2.5rem 0 1rem}h3{font-size:1rem;margin:1.25rem 0 .25rem}p{color:var(--muted)}
.legend{display:flex;flex-wrap:wrap;gap:.5rem 1.25rem;padding:0;list-style:none}.legend li{display:flex;align-items:center;gap:.5rem}
.swatch{width:.875rem;height:.875rem;display:inline-block}
.track{position:relative;height:1.75rem;background:var(--track) repeating-linear-gradient(90deg,transparent 0 calc(25% - 1px),var(--line) calc(25% - 1px) 25%);border:1px solid var(--line)}
.segment{position:absolute;top:0;height:100%;min-width:2px}.hours{display:flex;justify-content:space-between;font-size:.75rem;color:var(--muted)}
.worked{background:#24a148}.counted-break{background:#b28600}.call{background:#4589ff}.accepted{background:#a56eff}
.excluded-away{background:#da1e28}.unmatched,.interruption{background:#8d8d8d}
.scroll{overflow-x:auto}.scroll:focus-visible{outline:2px solid currentColor;outline-offset:2px}table{border-collapse:collapse;width:100%;min-width:36rem}.note{color:var(--muted);margin:0 0 .5rem}
th,td{border-bottom:1px solid var(--line);padding:.75rem 1rem;text-align:left;vertical-align:top}thead th{background:var(--layer)}
tbody th h3{margin:0}details{margin-top:2rem}summary{cursor:pointer}pre{white-space:pre-wrap;font:inherit;background:var(--layer);padding:1rem}
"""


def minutes_text(minutes):
    whole = round(minutes)
    return f"{whole // 60} h {whole % 60} min" if whole >= 60 else f"{whole} min"


REPORT_LABELS = {**LABELS, "worked": "worked", "counted-break": "short breaks counted",
                 "unmatched": "no client", "excluded-away": "time away left out"}


def long_date(day):
    return f"{day.strftime('%A')}, {day.day} {day.strftime('%B %Y')}"


def report_reasons(row):
    values = defaultdict(float)
    for s in row.segments:
        values[s.kind] += s.minutes
    parts = [f"{REPORT_LABELS[kind].capitalize()} {minutes_text(minutes)}" for kind, minutes in values.items()]
    if row.rounding:
        parts.append(f"Rounding {'added' if row.rounding > 0 else 'removed'} {minutes_text(abs(row.rounding))}")
    if row.held:
        parts.append(f"Monthly limit held back {minutes_text(row.held)}")
    return "; ".join(parts)


def html_review(result, projects, zone, titles=False, verbose=False):
    segments_all = timeline_segments(result)
    present = [kind for kind in LABELS if any(s.kind == kind for s in segments_all)]
    out = ['<!doctype html><html lang="en"><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           '<title>autohours review</title><style>', REPORT_STYLE, '</style><body><main><h1>autohours review</h1>',
           f'<p>Times are in {escape(str(zone))}. Each bar runs from midnight to midnight; the lines mark 6 AM, noon and 6 PM.</p>',
           '<p>Coloured blocks show the time counted for each client. Grey is activity that matched no client.'
           + ('' if titles else ' Window titles are left out of this report.') + '</p>',
           '<p>Monthly limits here count only activity on this computer. Writing also counts time already in your timesheet, so the written total can be lower.</p>',
           '<ul class="legend">']
    out.extend(f'<li><span class="swatch {kind}" aria-hidden="true"></span>{escape(REPORT_LABELS[kind].capitalize())}</li>' for kind in present)
    out.append('</ul>')
    groups = defaultdict(list)
    for s in segments_all:
        a = s.start
        while a < s.end:
            day = a.astimezone(zone).date()
            midnight = datetime.combine(day + timedelta(days=1), time(), zone).astimezone(timezone.utc)
            b = min(s.end, midnight)
            groups[(day, s.project)].append(replace(s, start=a, end=b))
            a = b
    shown_day = None
    for (day, project), segments in sorted(groups.items(), key=lambda item: (item[0][0], -1 if item[0][1] is None else item[0][1])):
        name = projects[project].name if project is not None else "No client"
        if day != shown_day:
            out.append(f'<h2>{long_date(day)}</h2>')
            shown_day = day
        out.append(f'<section><h3>{escape(name)}</h3><div class="track" aria-hidden="true">')
        a = datetime.combine(day, time(), zone).astimezone(timezone.utc)
        b = datetime.combine(day + timedelta(days=1), time(), zone).astimezone(timezone.utc)
        seconds = (b - a).total_seconds()
        compact = []
        for s in segments:
            if (compact and compact[-1].end == s.start and compact[-1].kind == s.kind
                    and (not titles or compact[-1].title == s.title)):
                compact[-1] = replace(compact[-1], end=s.end)
            else:
                compact.append(s)
        for s in compact:
            left = 100 * (s.start - a).total_seconds() / seconds
            width = 100 * (s.end - s.start).total_seconds() / seconds
            out.append(f'<span class="segment {s.kind}" style="left:{left:.5f}%;width:{width:.5f}%"></span>')
        out.append('</div><div class="hours" aria-hidden="true"><span>12 AM</span><span>6 AM</span><span>12 PM</span><span>6 PM</span><span>12 AM</span></div>')
        if verbose:
            out.append('<ul>')
            for s in compact:
                title = f" | {s.title}" if titles and s.title else ""
                label = f"{span(s.start, s.end, zone)}: {LABELS[s.kind]}, {s.minutes:.1f} min{title}"
                out.append(f'<li>{escape(label)}</li>')
            out.append('</ul>')
        out.append('</section>')
    out.append('<h2 id="entries-title">Entries</h2><p class="note" id="entries-note">What would be written to your timesheet. Gaps you were away are left out, so an entry can be shorter than the activity around it.</p><div class="scroll" role="region" aria-labelledby="entries-title" tabindex="0"><table aria-labelledby="entries-title" aria-describedby="entries-note"><thead><tr><th scope="col">Client</th><th scope="col">Activity</th><th scope="col">Entry</th><th scope="col">Billed</th><th scope="col">Details</th></tr></thead><tbody>')
    day = None
    for row in result.reviews:
        if not verbose and row.billed <= 0:
            continue
        local_day = row.start.astimezone(zone).date()
        if local_day != day:
            if day is not None:
                out.append('</tbody><tbody>')
            out.append(f'<tr><th colspan="5" scope="rowgroup"><h3>{long_date(local_day)}</h3></th></tr>')
            day = local_day
        activity_span = span(row.start, row.end, zone)
        entry = span(row.entry_start, row.entry_start + timedelta(minutes=row.billed), zone) if row.billed else "Not written"
        detail = report_reasons(row) if not verbose else reasons(row)
        if titles:
            detail += " | " + " | ".join(sorted({s.title for s in row.segments if s.title}))
        out.append(f'<tr><th scope="row">{escape(projects[row.project].name)}</th><td>{escape(activity_span)}</td><td>{escape(entry)}</td><td>{minutes_text(row.billed)}</td><td>{escape(detail)}</td></tr>')
    out.append('</tbody></table></div>')
    out.append('<h2 id="totals-title">Totals</h2><p class="note" id="totals-note">Billed time and the agreement for each client.</p><div class="scroll" role="region" aria-labelledby="totals-title" tabindex="0"><table aria-labelledby="totals-title" aria-describedby="totals-note"><thead><tr><th scope="col">Client</th><th scope="col">Billed</th><th scope="col">Agreement</th></tr></thead><tbody>')
    for name, minutes, detail in totals(result, projects):
        out.append(f'<tr><th scope="row">{escape(name)}</th><td>{minutes_text(minutes)}</td><td>{escape(detail)}</td></tr>')
    out.append('</tbody></table></div><details><summary>Calculation details</summary><pre>')
    out.append(escape("\n".join(summary_lines(result, projects, titles))))
    out.append('</pre></details></main></body></html>')
    return "\n".join(out)
