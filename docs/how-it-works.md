# How matching and billing work

```text
ActivityWatch on your computer
  -> match your project rules
  -> validate activity and accepted work
  -> apply the project agreement
  -> build daily blocks
  -> preview
  -> Clockify or CSV, only after you confirm
```

autohours supports ActivityWatch, Clockify and CSV. Small source and destination interfaces leave room for future integrations such as Toggl and Harvest. See [adding a destination](adding-a-destination.md).

## Matching and blocks

Each project can contain lists of regular expressions in `title`, `app` and `url`. Any matching rule is enough. All rules ignore letter case. **The first matching project wins. Put specific projects above general ones.** There is no automatic project guessing and no AI service in the program.

Use single-quoted TOML strings for regexes, for example `url = ['^https://acme\.example/']`. An app rule matches every use of that app, so use broad app rules carefully. `rules test` checks an example without contacting ActivityWatch or Clockify.

By default, only intervals marked `not-afk` count as work. Explicit accepted time and agreed calls while away are exceptions. Missing AFK data is not assumed active or an agreed short break. Overlapping events are counted once. Each project's actual worked seconds are retained, even when several projects share a calendar minute. Unmatched seconds are never reassigned to a project. Explicit accepted time takes precedence at its exact boundaries, including partial minutes.

Slices for the same project merge across interruptions when each gap between that project's slices is at most `merge_gap_minutes` (default 5). This includes unmatched windows, another project's work and away time. Merging groups an entry; it never bills those interruptions to the project. Billed minutes are the project's worked minutes plus explicitly counted breaks, calls and accepted time. A 30-minute span with a 3-minute away gap bills 27 minutes by default, or 30 when `count_breaks_up_to_minutes = 5`. Unknown gaps remain excluded even with a break policy. Another project's interruption counts only toward that project's own merged block; if that block is too short, its time is filtered out.

Entries run from their entry start to entry start plus billed duration. When merged projects have overlapping activity spans, their compressed entries are placed in first-seen order, shifting a later entry's start forward as needed to avoid overlap. Review shows both the real activity span and the destination entry. Blocks split at local midnight. `min_block_minutes` (default 10) applies to the merged block's billed duration after rounding, not its individual fragments. Explicitly accepted blocks bypass the minimum when rounding leaves a positive duration. Unmatched and filtered time are reported separately.

`round_to_minutes = 0` disables rounding. Otherwise rounding applies to billed duration per entry, using `nearest` (ties up) or `up`. Project agreement settings override policy defaults, then `blocks.round_to_minutes`. Rounding reserves other interleaved projects' work and is clipped at the next separate block, local midnight or the end of the requested period, so entries cannot overlap or extend into the future. Review reports the actual minutes added or removed.

Clockify and CSV skip an entire block if any of it overlaps an existing entry. Touching endpoints are fine. Manual entries and running Clockify timers take precedence. Repeating a completed sync does not duplicate its blocks. Clockify scans earlier entries too, so an entry beginning before the selected day is still protected; this can be slow for large histories. Do not run two writers at once: the remote API does not offer an atomic overlap check, and a concurrent manual edit can race a sync. If a write fails partway through, preview and retry; completed entries will be skipped.

## Billing agreements

Add `[projects.agreement]` directly below a project's rules. All agreement fields are optional and can also be defaults in `[policy]`. The examples are fictional:

```toml
[projects.agreement]
billing = "hourly"
rate = 120
currency = "CAD"
count_breaks_up_to_minutes = 5
count_calls_when_away = true
round_to_minutes = 5
rounding = "up"
monthly_cap_hours = 40
```

Billing can be `hourly`, `flat`, `retainer` or `none`. A billing type sets the destination billable flag: all except `none` are billable. Without a billing type, the existing project `billable` setting applies. Flat and retainer agreements track time without calculating an hourly charge. Neither a rate nor a currency is ever assumed. Hourly projects without a rate say "rate not set"; without a currency, amount calculation and rate updates are disabled.

Short-break policies count only observed AFK gaps inside a merged block, up to and including the configured limit. Calls count while away only when the foreground window matches a project and a `policy.call_apps` or `policy.call_titles` regex. Defaults recognize Zoom, Google Meet, Microsoft Teams, Slack huddle and Discord; customize them for the actual watcher values. Calls still need AFK evidence. Missing data does not become work automatically.

**What if my laptop sleeps?** No watcher data means no observed activity. Gaps longer than the merge setting stay separate. Grouped gaps remain unbilled unless they qualify under an explicit agreement.

## Privacy details

**Window titles and URLs never go to a timesheet destination through autohours. Only project name or ID, your fixed description, times and billable status go to the destination.** CSV adds date and calculated minutes. The program accepts only a local ActivityWatch URL, performs no telemetry and creates no activity cache. Web data is opt-in. Destination records have no raw title or URL fields.

Unmatched titles appear in your local terminal so you can improve rules. Terminal logs, screenshots, or content you paste into Claude Code or Codex can expose those titles. Review and redact before sharing. Keep your descriptions free of private details you do not want in a timesheet. autohours does not control ActivityWatch's own storage or other tools' data handling. Remove CSV files and manage retention in ActivityWatch and Clockify when no longer needed. The repository ignores your root config, accepted-time file and default CSV. Keep HTML reviews and any custom export paths outside the repository.

## Scheduling

After reviewing a successful manual write, the setup wizard can schedule `autohours sync yesterday --write` daily. It previews the commands and asks for separate approval. It uses absolute paths, the installed Python environment, and your user account. Remove its daily job with `autohours schedule --remove`. See [Windows, macOS and Linux examples](scheduling.md) for manual alternatives. Run only one scheduled instance for each destination.
