# autohours

Turn automatic computer activity tracking into timesheet entries you can review before writing.

```text
ActivityWatch on your computer
  -> keep non-AFK time
  -> match your project rules
  -> build daily blocks
  -> preview
  -> Clockify or CSV, only with --write
```

Version 1 supports ActivityWatch, Clockify and CSV. Small source and destination interfaces leave room for future integrations such as Toggl and Harvest.

## Requirements

- Windows, macOS or Linux, with Python 3.11 or newer.
- [ActivityWatch](https://activitywatch.net/) running with its window and AFK watchers enabled.
- A Clockify account for Clockify exports, or just a local folder for CSV.
- IANA timezone data. macOS and Linux usually include it. On Windows, run `python -m pip install tzdata` in the same environment as autohours, or `pipx inject autohours tzdata` after a pipx install. This is timezone data for Python's standard `zoneinfo`, not an application library dependency.

The application uses only Python's standard library, plus the `tzdata` time zone package on Windows. pytest is for development only. Wayland desktop restrictions can prevent ActivityWatch from capturing window titles; check its dashboard before setup.

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
   autohours preview yesterday
   autohours sync yesterday
   autohours sync yesterday --write
   ```

`preview` needs no Clockify key. `sync` without `--write` prints the same preview and checks existing destination entries. `init` creates only the starter config and refuses to overwrite it. No timesheet entry or CSV file is written unless `--write` is passed.

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

Only intervals marked `not-afk` are classified. Missing AFK data is not assumed active. Overlapping events are counted once. Each UTC minute has at most one assigned project, chosen by greatest active duration; ties follow config order. Unmatched time participates in this choice and wins if it has more duration. Losing project slices are dropped, never reassigned. Actual seconds of the winning project are retained, not expanded to full minutes.

Consecutive slices for the same project merge when the gap is at most `merge_gap_minutes` (default 5). **Bridged missing/AFK gaps count toward the elapsed block. Set this to 0 if you want strictly observed active time.** Unmatched activity and other projects break the block. Blocks split at local midnight and those shorter than `min_block_minutes` (default 10) are discarded. The preview reports unmatched and filtered time separately.

`round_to_minutes = 0` disables rounding. A positive value trims the start up and end down to UTC multiples of that many minutes, then applies the minimum length. It never expands blocks or introduces overlapping projects. This conservative rule may remove short blocks. Around timezone offsets, the grid may differ from local clock multiples.

Clockify and CSV skip an entire block if any of it overlaps an existing entry. Touching endpoints are fine. Manual entries and running Clockify timers take precedence. Repeating a completed sync does not duplicate its blocks. Clockify scans earlier entries too, so an entry beginning before the selected day is still protected; this can be slow for large histories. Do not run two writers at once: the remote API does not offer an atomic overlap check, and a concurrent manual edit can race a sync. If a write fails partway through, preview and retry; completed entries will be skipped.

## Privacy

**Window titles and URLs never leave the machine through autohours. Only project name or ID, your fixed description, times and billable status go to the destination.** CSV adds date and calculated minutes. The program accepts only a local ActivityWatch URL, performs no telemetry and creates no activity cache. Web data is opt-in. Destination records have no raw title or URL fields.

Unmatched titles appear in your local terminal so you can improve rules. Terminal logs, screenshots, or content you paste into Claude Code or Codex can expose those titles. Review and redact before sharing. Keep your descriptions free of private details you do not want in a timesheet. autohours does not control ActivityWatch's own storage or other tools' data handling. Remove CSV files and manage retention in ActivityWatch and Clockify when no longer needed. The repository ignores your root config and default CSV.

## Scheduling

After reviewing a successful manual write, schedule `autohours sync yesterday --write` daily. Use an absolute config path, the installed executable's full path, and a scheduler account with the API key available. See [Windows, macOS and Linux examples](docs/scheduling.md). Run only one scheduled instance for each destination.

## Set it up with Claude Code or Codex

For Claude Code, copy `skills/autohours-setup/` from this repository into `~/.claude/skills/`. On Windows this is inside your user folder. Then ask: "Use autohours-setup to help me turn my ActivityWatch activity into timesheets."

Codex and other agents can use [AGENTS.md](AGENTS.md). Ask them to inspect a few days of unmatched activity locally, propose project rules and show a preview. Review before approving the first `--write`. The [setup skill](skills/autohours-setup/SKILL.md) walks through this process without assuming you are a programmer.

## FAQ

**What if my laptop sleeps?** No watcher data means no observed activity. Gaps longer than the merge setting stay separate. Short gaps may be bridged, so use a zero merge gap for strict active time.

**Can I use multiple computers?** Select `activitywatch.hostname` when a server contains multiple window buckets. Run separately on each computer with the same destination. Existing overlaps win; simultaneous activity is not combined, and simultaneous syncs are not supported.

**Does this track my phone or offline work?** No. Add calls, travel and other untracked work manually. Those entries take precedence on the next sync.

**How do I match browser URLs?** Install the ActivityWatch browser extension and set `use_web = true`. Web buckets must identify the selected hostname, and the event title must match the foreground window title after removing a standard browser-name suffix. This conservative check avoids attributing background tabs; unusual browser-added title suffixes can prevent URL matching. Use title rules when URL coverage is incomplete. Incognito web events are not used for URL matching.

**Why is my preview empty?** Check ActivityWatch's dashboard, run `doctor`, then `unmatched yesterday`. Confirm the timezone, host, AFK watcher, regexes and minimum block length.

**Can I undo a sync?** Review or delete entries in Clockify, or edit your CSV. autohours does not delete destination entries. Back up a CSV before editing it. CSV start and end include full dates and offsets; keep those columns intact for overlap checking.

**Is CSV safe to open in a spreadsheet?** It contains your configured project names and descriptions verbatim. Do not use untrusted formula-like text in those fields if your spreadsheet evaluates formulas on import.

## Contributing

```sh
python -m pip install -e ".[dev]"
python -m pytest
```

Install `tzdata` in the test environment if your OS lacks IANA data. Tests are fully offline and use synthetic events and stubbed HTTP. CI covers Python 3.11 and 3.13 on Windows, macOS and Linux. Keep runtime code standard-library-only, avoid raw activity in destination objects, and add regression tests for changed behavior. See [adding a destination](docs/adding-a-destination.md). The package and command metadata live in `pyproject.toml`; shared display and config names live in `src/autohours/__init__.py`.

API references: [ActivityWatch REST API](https://docs.activitywatch.net/en/latest/api/rest.html) and [Clockify API](https://docs.clockify.me/).
