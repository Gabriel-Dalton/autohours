# Command line and settings file

Everything the desktop app does is also available from a terminal. The app and the terminal share the same settings file.

## Requirements

- Windows, macOS or Linux. Terminal installs need Python 3.11 or newer. Downloads include Python. Use a browser already on your computer.
- [ActivityWatch](https://activitywatch.net/) running with its window and AFK watchers enabled.
- A Clockify account for Clockify exports, or just a local folder for CSV.

The application uses only Python's standard library, plus the `tzdata` time zone package, which is installed automatically on Windows. pytest is for development only. PyInstaller is only in the optional `build` extra. Wayland desktop restrictions can prevent ActivityWatch from capturing window titles; check its dashboard before setup.

## Set up with terminal questions

After installing, `autohours` opens the desktop app. For questions in the terminal instead, run:

```sh
autohours setup
```

The wizard helps you open ActivityWatch, confirm your time zone, choose Clockify or a spreadsheet, and pick activity that belongs to each client. You choose numbered items and confirm keywords. You never need to edit a file or write a regular expression. It asks about each project's billing agreement one question at a time, without assuming a rate or currency.

Press Enter for a bracketed default. Type `back` to revisit the previous answer or `quit` to stop; Ctrl+C also exits cleanly. Your config stays unchanged until you confirm the summary. Once a change is saved, going back does not undo it. Existing configs offer adding a project or starting over. To add a project directly:

```sh
autohours setup --add-project
```

Clockify setup asks for your key using hidden input. Find it in **Profile settings > API > Generate**. Never paste it into chat. The key never goes in `autohours.toml`. Windows saves `CLOCKIFY_API_KEY` in your user environment. macOS/Linux save a private `credentials` file beside the default user config, with permissions 600. Environment variables take priority. To remove the saved key, delete the Windows user environment variable, or delete the credentials file and unset any shell variable. Revoke the key in Clockify if needed.

Setup checks your settings, shows rate differences when applicable, and reviews yesterday (or today if yesterday has no matching blocks). It asks separately before applying rates, writing that day's entries, or scheduling daily writes. The schedule defaults to 6:00 AM on your computer's clock. To remove it:

```sh
autohours schedule --remove
```

The last seven days' activity list contains private local window titles. Do not share it without reviewing it. Matching rules stay local. Only fixed descriptions and approved times go to the destination.

## Edit the config yourself

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

   Alternatively, use `pipx install .`, or `pipx install git+https://github.com/Gabriel-Dalton/autohours`. If your system calls Python `python3`, use that instead of `python`.

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

   Use exact Clockify project names in `destination_project`, or omit it when `name` is already correct. The [fully commented example](../examples/autohours.example.toml) explains every field.

6. Check, review, then write:

   ```sh
   autohours doctor
   autohours review yesterday
   autohours preview yesterday
   autohours sync yesterday
   autohours sync yesterday --write
   ```

`preview` needs no Clockify key. `sync` without `--write` checks existing destination entries and prints the proposed entries after destination cap accounting. `init` creates only the starter config and refuses to overwrite it. Manual commands write timesheets only with `--write`. The setup wizard runs it only after a separate yes.

## Commands and config location

```sh
autohours preview
autohours preview 2026-10-14 2026-10-16
autohours unmatched yesterday
autohours rules test "Acme planning" --app "Browser" --url "https://acme.example/"
autohours --config /path/to/autohours.toml sync yesterday --write
```

The default date is today. Two dates include both the start and end day, in your configured timezone. Today stops at the current time. Future-only periods are rejected. Reviews show dates as headings and local times such as `10:23 to 11:32`. Repeated daylight saving hours include offsets so they remain distinguishable.

The global `--config PATH` option goes before the command. Otherwise, autohours checks `./autohours.toml`, then:

| System | User config path |
| --- | --- |
| Windows | `%APPDATA%\autohours\autohours.toml` |
| macOS | `~/Library/Application Support/autohours/autohours.toml` |
| Linux | `$XDG_CONFIG_HOME/autohours/autohours.toml`, or `~/.config/autohours/autohours.toml` |

Relative CSV paths are resolved beside the config file, so a scheduler's working directory will not change the export location.

## Accepted time, reviews and rates

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

`rates` compares agreement billable flags and hourly rates with Clockify. Only `--apply` changes project settings, then reads them back and reports mismatches. Confirm the exact values first. A workspace currency mismatch refuses that project's update; autohours never changes workspace currency or invents a rate. See [Clockify endpoints and rate limitations](clockify.md).

Clockify invoicing is a [paid feature](https://clockify.me/help/projects/invoicing-tracked-time-expenses). autohours works with the free plan for time entries; it does not create invoices.

## Set it up with Claude Code or Codex

For Claude Code, copy `skills/autohours-setup/` from this repository into `~/.claude/skills/`. On Windows this is inside your user folder. Then ask: "Use autohours-setup to help me turn my ActivityWatch activity into timesheets."

Codex and other agents can use [AGENTS.md](../AGENTS.md). Prefer `autohours setup` in your own terminal. Agents can walk through the same questions and edit the config on your behalf; you should never have to write a regex. If you want help choosing rules, let them inspect a few days of unmatched activity locally and show a preview. Review before approving the first `--write`. The [setup skill](../skills/autohours-setup/SKILL.md) walks through this process without assuming you are a programmer.

## More questions

**Can I use multiple computers?** Select `activitywatch.hostname` when a server contains multiple window buckets. Run separately on each computer with the same destination. Existing overlaps win; simultaneous activity is not combined, and simultaneous syncs are not supported.

**Does this track my phone or offline work?** It does not observe that work. Use `accept` for specific work you confirm, or add entries manually in your destination. Existing destination entries take precedence on the next sync.

**How do I match browser URLs?** Install the ActivityWatch browser extension and set `use_web = true`. Web buckets must identify the selected hostname, and the event title must match the foreground window title after removing a standard browser-name suffix. This conservative check avoids attributing background tabs; unusual browser-added title suffixes can prevent URL matching. Use title rules when URL coverage is incomplete. Incognito web events are not used for URL matching.

**Why is my preview empty?** Check ActivityWatch's dashboard, run `doctor`, then `unmatched yesterday`. Confirm the timezone, host, AFK watcher, regexes and minimum block length.

**Can I undo a sync?** Review or delete entries in Clockify, or edit your CSV. autohours does not delete destination entries. Back up a CSV before editing it. CSV start and end include full dates and offsets; keep those columns intact for overlap checking.

**Is CSV safe to open in a spreadsheet?** It contains your configured project names and descriptions verbatim. Do not use untrusted formula-like text in those fields if your spreadsheet evaluates formulas on import.
