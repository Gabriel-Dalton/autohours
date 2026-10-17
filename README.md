# autohours

Validate timesheets against ActivityWatch and bill time the way your client agreement says. Review the evidence before writing.

```text
ActivityWatch on your computer
  -> match your project rules
  -> validate activity and accepted work
  -> apply the project agreement
  -> build daily blocks
  -> preview
  -> Clockify or CSV, only with --write
```

autohours supports ActivityWatch, Clockify and CSV. Small source and destination interfaces leave room for future integrations such as Toggl and Harvest.

## Requirements

- Windows, macOS or Linux, with Python 3.11 or newer.
- [ActivityWatch](https://activitywatch.net/) running with its window and AFK watchers enabled.
- A Clockify account for Clockify exports, or just a local folder for CSV.

The application uses only Python's standard library, plus the `tzdata` time zone package, which is installed automatically on Windows. pytest is for development only. Wayland desktop restrictions can prevent ActivityWatch from capturing window titles; check its dashboard before setup.

## Five-minute quickstart

1. Install and open ActivityWatch. Visit `http://localhost:5600` and check that it records windows and active time. You need some recorded activity before previews are useful.
2. For Clockify, create your workspace and projects, then get an API key from **Profile settings**. Skip this step for CSV.
3. Set the key in your terminal. Replace the placeholder locally; never save your key in the config or a repository.

   Windows PowerShell:

   ```powershell
   $env:CLOCKIFY_API_KEY = "YOUR_API_KEY"
   ```

   macOS or Linux:

   ```sh
   export CLOCKIFY_API_KEY='YOUR_API_KEY'
   ```

   These commands affect this terminal session. Scheduled tasks need their own environment setup.

4. In a downloaded or cloned copy of this repository, install:

   ```sh
   python -m pip install .
   ```

   Alternatively, use `pipx install .`, or `pipx install git+https://YOUR_REPOSITORY_URL`. Replace the URL with the actual published Git repository URL. If your system calls Python `python3`, use that instead of `python`.

5. Create and edit your settings:

   ```sh
   autohours init
   ```

   Open `autohours.toml` in a text editor. Set your timezone and real project rules. It starts with CSV. For Clockify, replace `[destination]` with:

   ```toml
   [destination]
   type = "clockify"
   workspace = "My workspace"
   ```

   Use exact Clockify project names in `destination_project`, or omit it when `name` is already correct. The [fully commented example](examples/autohours.example.toml) explains every field.

6. Check, review, then write:

   ```sh
   autohours doctor
   autohours review yesterday
   autohours preview yesterday
   autohours sync yesterday
   autohours sync yesterday --write
   ```

`preview` needs no Clockify key. `sync` without `--write` checks existing destination entries and prints the proposed entries after destination cap accounting. `init` creates only the starter config and refuses to overwrite it. No timesheet entry or CSV file is written unless `--write` is passed.

## Commands and config location

```sh
autohours preview
autohours preview 2026-10-14 2026-10-16
autohours unmatched yesterday
autohours rules test "Acme planning" --app "Browser" --url "https://acme.example/"
autohours --config /path/to/autohours.toml sync yesterday --write
```

The default date is today. Two dates include both the start and end day, in your configured timezone. Today stops at the current time. Future-only periods are rejected. Previews include offsets to distinguish repeated hours when daylight saving time ends.

The global `--config PATH` option goes before the command. Otherwise, autohours checks `./autohours.toml`, then:

| System | User config path |
| --- | --- |
| Windows | `%APPDATA%\autohours\autohours.toml` |
| macOS | `~/Library/Application Support/autohours/autohours.toml` |
| Linux | `$XDG_CONFIG_HOME/autohours/autohours.toml`, or `~/.config/autohours/autohours.toml` |

Relative CSV paths are resolved beside the config file, so a scheduler's working directory will not change the export location.

## How matching and blocks work

Each project can contain lists of regular expressions in `title`, `app` and `url`. Any matching rule is enough. All rules ignore letter case. **The first matching project wins. Put specific projects above general ones.** There is no automatic project guessing and no AI service in the program.

Use single-quoted TOML strings for regexes, for example `url = ['^https://acme\.example/']`. An app rule matches every use of that app, so use broad app rules carefully. `rules test` checks an example without contacting ActivityWatch or Clockify.

By default, only intervals marked `not-afk` count as work. Explicit accepted time and agreed calls while away are exceptions. Missing AFK data is not assumed active or an agreed short break. Overlapping events are counted once. Each project's actual worked seconds are retained, even when several projects share a calendar minute. Unmatched seconds are never reassigned to a project. Explicit accepted time takes precedence at its exact boundaries, including partial minutes.

Slices for the same project merge across interruptions when each gap between that project's slices is at most `merge_gap_minutes` (default 5). This includes unmatched windows, another project's work and away time. Merging groups an entry; it never bills those interruptions to the project. Billed minutes are the project's worked minutes plus explicitly counted breaks, calls and accepted time. A 30-minute span with a 3-minute away gap bills 27 minutes by default, or 30 when `count_breaks_up_to_minutes = 5`. Unknown gaps remain excluded even with a break policy. Another project's interruption counts only toward that project's own merged block; if that block is too short, its time is filtered out.

Entries run from their entry start to entry start plus billed duration. When merged projects have overlapping activity spans, their compressed entries are placed in first-seen order, shifting a later entry's start forward as needed to avoid overlap. Review shows both the real activity span and the destination entry. Blocks split at local midnight. `min_block_minutes` (default 10) applies to the merged block's billed duration after rounding, not its individual fragments. Explicitly accepted blocks bypass the minimum when rounding leaves a positive duration. Unmatched and filtered time are reported separately.

`round_to_minutes = 0` disables rounding. Otherwise rounding applies to billed duration per entry, using `nearest` (ties up) or `up`. Project agreement settings override policy defaults, then `blocks.round_to_minutes`. Rounding reserves other interleaved projects' work and is clipped at the next separate block, local midnight or the end of the requested period, so entries cannot overlap or extend into the future. Review reports the actual minutes added or removed.

Clockify and CSV skip an entire block if any of it overlaps an existing entry. Touching endpoints are fine. Manual entries and running Clockify timers take precedence. Repeating a completed sync does not duplicate its blocks. Clockify scans earlier entries too, so an entry beginning before the selected day is still protected; this can be slow for large histories. Do not run two writers at once: the remote API does not offer an atomic overlap check, and a concurrent manual edit can race a sync. If a write fails partway through, preview and retry; completed entries will be skipped.

## Bill it the way you agreed

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

```sh
autohours accept 2026-10-14 14:00 14:30 --project "Acme Corp" --note "Confirmed call"
autohours accepted 2026-10-14
autohours accept --remove ACCEPTED_ID
autohours review 2026-10-14 2026-10-16
autohours review yesterday --html review.html
autohours review yesterday --verbose
autohours rates
autohours rates --apply
```

Accepted time is your explicit confirmation of work regardless of AFK. It is saved in `autohours.accepted.toml` beside your config. Use local `HH:MM` times on one date; repeated DST times need an offset such as `01:30-07:00`. Overlapping accepted blocks are rejected. Acceptance replaces overlapping observed evidence, so time is counted once. Notes stay local and never become a destination description. Removing acceptance does not remove destination entries. Existing destination overlaps still win.

Preview and review share the same output: billed blocks with explanations, filtered time per project, the top 10 unmatched apps by total time, then totals. Use `--verbose` for filtered blocks and individual activity segments. Both commands accept `--titles` to include private window titles and group unmatched time by app and title. Blocks show real spans, destination entry times, worked and billed minutes, excluded interruptions, counted breaks, calls, accepted time, rounding and caps. Hourly totals show rate x hours = amount, without combining currencies.

HTML is one self-contained accessible file with day timelines, a block table and totals. Adjacent timeline segments of the same kind are combined regardless of title unless titles are requested. Individual segment listings require `--verbose`. The file makes no external requests. Window titles are omitted unless `--titles` is passed; descriptions, URLs and accepted notes are omitted too. Unmatched app names, project names, rates and totals may still be confidential, so review the file before sharing it.

Caps apply per project and calendar month in your timezone. Preview and review allocate the month's local evidence chronologically up to the selected end date, even when you select a later day. They warn and show what would be held back. Sync instead reserves existing destination time for the whole month, including manual entries, then allocates the remaining cap to new entries in date order. A partial final entry may be shorter than the rounding quantum or minimum. Overlapping entries are skipped before consuming any further cap. Clockify caps cover the signed-in user's entries, not other workspace members. Run a dry sync to see the destination-aware cap decision; it can differ from the local review. Avoid concurrent writers.

`rates` compares agreement billable flags and hourly rates with Clockify. Only `--apply` changes project settings, then reads them back and reports mismatches. Confirm the exact values first. A workspace currency mismatch refuses that project's update; autohours never changes workspace currency or invents a rate. See [Clockify endpoints and rate limitations](docs/clockify.md).

Clockify invoicing is a [paid feature](https://clockify.me/help/projects/invoicing-tracked-time-expenses). autohours works with the free plan for time entries; it does not create invoices.

## Privacy

**Window titles and URLs never go to a timesheet destination through autohours. Only project name or ID, your fixed description, times and billable status go to the destination.** CSV adds date and calculated minutes. The program accepts only a local ActivityWatch URL, performs no telemetry and creates no activity cache. Web data is opt-in. Destination records have no raw title or URL fields.

Unmatched titles appear in your local terminal so you can improve rules. Terminal logs, screenshots, or content you paste into Claude Code or Codex can expose those titles. Review and redact before sharing. Keep your descriptions free of private details you do not want in a timesheet. autohours does not control ActivityWatch's own storage or other tools' data handling. Remove CSV files and manage retention in ActivityWatch and Clockify when no longer needed. The repository ignores your root config, accepted-time file and default CSV. Keep HTML reviews and any custom export paths outside the repository.

## Scheduling

After reviewing a successful manual write, schedule `autohours sync yesterday --write` daily. Use an absolute config path, the installed executable's full path, and a scheduler account with the API key available. See [Windows, macOS and Linux examples](docs/scheduling.md). Run only one scheduled instance for each destination.

## Set it up with Claude Code or Codex

For Claude Code, copy `skills/autohours-setup/` from this repository into `~/.claude/skills/`. On Windows this is inside your user folder. Then ask: "Use autohours-setup to help me turn my ActivityWatch activity into timesheets."

Codex and other agents can use [AGENTS.md](AGENTS.md). Ask them to inspect a few days of unmatched activity locally, propose project rules and show a preview. Review before approving the first `--write`. The [setup skill](skills/autohours-setup/SKILL.md) walks through this process without assuming you are a programmer.

## FAQ

**What if my laptop sleeps?** No watcher data means no observed activity. Gaps longer than the merge setting stay separate. Grouped gaps remain unbilled unless they qualify under an explicit agreement.

**Can I use multiple computers?** Select `activitywatch.hostname` when a server contains multiple window buckets. Run separately on each computer with the same destination. Existing overlaps win; simultaneous activity is not combined, and simultaneous syncs are not supported.

**Does this track my phone or offline work?** It does not observe that work. Use `accept` for specific work you confirm, or add entries manually in your destination. Existing destination entries take precedence on the next sync.

**How do I match browser URLs?** Install the ActivityWatch browser extension and set `use_web = true`. Web buckets must identify the selected hostname, and the event title must match the foreground window title after removing a standard browser-name suffix. This conservative check avoids attributing background tabs; unusual browser-added title suffixes can prevent URL matching. Use title rules when URL coverage is incomplete. Incognito web events are not used for URL matching.

**Why is my preview empty?** Check ActivityWatch's dashboard, run `doctor`, then `unmatched yesterday`. Confirm the timezone, host, AFK watcher, regexes and minimum block length.

**Can I undo a sync?** Review or delete entries in Clockify, or edit your CSV. autohours does not delete destination entries. Back up a CSV before editing it. CSV start and end include full dates and offsets; keep those columns intact for overlap checking.

**Is CSV safe to open in a spreadsheet?** It contains your configured project names and descriptions verbatim. Do not use untrusted formula-like text in those fields if your spreadsheet evaluates formulas on import.

## Contributing

```sh
python -m pip install -e ".[dev]"
python -B -m pytest -p no:cacheprovider
```

Tests are fully offline and use synthetic events and stubbed HTTP. CI covers Python 3.11 and 3.13 on Windows, macOS and Linux. Keep runtime code standard-library-only (tzdata on Windows is the one exception), avoid raw activity in destination objects, and add regression tests for changed behavior. See [adding a destination](docs/adding-a-destination.md). The package and command metadata live in `pyproject.toml`; shared display and config names live in `src/autohours/__init__.py`.

API references: [ActivityWatch REST API](https://docs.activitywatch.net/en/latest/api/rest.html) and [Clockify API](https://docs.clockify.me/).
