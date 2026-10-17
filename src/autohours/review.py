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
    return value.astimezone(zone).isoformat(timespec="seconds")


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
    if not result.blocks:
        lines.append("No matching blocks. Check your rules, minimum block length and AFK watcher.")
    for row in result.reviews:
        if not verbose and row.billed <= 0:
            continue
        worked = sum(s.minutes for s in row.segments if s.kind in ("worked", "call", "accepted"))
        lines.append(f"{stamp(row.start, zone)} to {stamp(row.end, zone)}  {safe(projects[row.project].name)}  worked {worked:.1f} min; billed {row.billed:.1f} min")
        lines.append("  " + reasons(row))
        if row.billed:
            entry_end = row.entry_start + timedelta(minutes=row.billed)
            lines.append(f"  Entry: {stamp(row.entry_start, zone)} to {stamp(entry_end, zone)}")
        if titles:
            lines.extend("  " + safe(title) for title in sorted({s.title for s in row.segments if s.title}))
    if verbose:
        lines.append("Activity detail:")
        for s in timeline_segments(result):
            name = projects[s.project].name if s.project is not None else "Unmatched"
            lines.append(f"  {stamp(s.start, zone)} to {stamp(s.end, zone)}  {safe(name)}: {LABELS[s.kind]}, {s.minutes:.1f} min")
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


def html_review(result, projects, zone, titles=False, verbose=False):
    out = ['<!doctype html><html lang="en"><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width, initial-scale=1">',
           '<title>autohours review</title><style>',
           ':root{color-scheme:light dark}body{font:16px system-ui,sans-serif;max-width:75rem;margin:auto;padding:2rem;line-height:1.5}',
           'table{border-collapse:collapse;width:100%}th,td{border:1px solid #888;padding:.6rem;text-align:left}',
           '.track{position:relative;height:2rem;border:1px solid #888;margin:1rem 0}.segment{position:absolute;height:100%;min-width:2px}',
           '.worked{background:#217a46}.counted-break{background:#a66b00}.call{background:#246bc4}.accepted{background:#964cc2}',
           '.excluded-away{background:#ae4646}.unmatched,.interruption{background:#666}.key{display:inline-block;padding:.1rem .5rem;color:white;margin:.25rem}',
           'pre{white-space:pre-wrap;font:inherit}li{margin:.3rem 0}</style><body><main><h1>autohours review</h1>',
           '<p>Real activity spans are shown below. Destination entries compress excluded gaps. Rounding and caps change billed totals.</p>',
           '<p>Caps in this local review use ActivityWatch and accepted time. Dry sync also checks logged destination time.</p>',
           '<h2>Legend</h2><ul>']
    out.extend(f'<li><span class="key {kind}">{escape(label)}</span></li>' for kind, label in LABELS.items())
    out.append('</ul>')
    groups = defaultdict(list)
    for s in timeline_segments(result):
        a = s.start
        while a < s.end:
            day = a.astimezone(zone).date()
            midnight = datetime.combine(day + timedelta(days=1), time(), zone).astimezone(timezone.utc)
            b = min(s.end, midnight)
            groups[(day, s.project)].append(replace(s, start=a, end=b))
            a = b
    for (day, project), segments in sorted(groups.items(), key=lambda item: (item[0][0], -1 if item[0][1] is None else item[0][1])):
        name = projects[project].name if project is not None else "Unmatched"
        out.append(f'<section><h2>{day} {escape(name)}</h2><p>Local midnight to midnight ({escape(str(zone))})</p><div class="track" aria-hidden="true">')
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
        out.append('</div>')
        if verbose:
            out.append('<ul>')
            for s in compact:
                title = f" | {s.title}" if titles and s.title else ""
                label = f"{stamp(s.start, zone)} to {stamp(s.end, zone)}: {LABELS[s.kind]}, {s.minutes:.1f} min{title}"
                out.append(f'<li>{escape(label)}</li>')
            out.append('</ul>')
        out.append('</section>')
    out.append('<h2>Blocks</h2><table><caption>Real spans and compressed destination entries</caption><thead><tr><th scope="col">Project</th><th scope="col">Activity span</th><th scope="col">Entry</th><th scope="col">Billed minutes</th><th scope="col">Explanation</th></tr></thead><tbody>')
    for row in result.reviews:
        if not verbose and row.billed <= 0:
            continue
        span = f"{stamp(row.start, zone)} to {stamp(row.end, zone)}"
        entry = f"{stamp(row.entry_start, zone)} to {stamp(row.entry_start + timedelta(minutes=row.billed), zone)}" if row.billed else "Not written"
        detail = reasons(row)
        if titles:
            detail += " | " + " | ".join(sorted({s.title for s in row.segments if s.title}))
        out.append(f'<tr><th scope="row">{escape(projects[row.project].name)}</th><td>{escape(span)}</td><td>{escape(entry)}</td><td>{row.billed:.1f}</td><td>{escape(detail)}</td></tr>')
    out.append('</tbody></table><h2>Summary</h2><pre>')
    out.append(escape("\n".join(summary_lines(result, projects, titles))))
    out.append('</pre>')
    out.append('<h2>Totals</h2><table><caption>Billed time and agreed rates</caption><thead><tr><th scope="col">Project</th><th scope="col">Minutes</th><th scope="col">Agreement</th></tr></thead><tbody>')
    for name, minutes, detail in totals(result, projects):
        out.append(f'<tr><th scope="row">{escape(name)}</th><td>{minutes:.1f}</td><td>{escape(detail)}</td></tr>')
    out.append('</tbody></table></main></body></html>')
    return "\n".join(out)
