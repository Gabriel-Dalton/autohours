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

## Quick start

Choose the way that feels easiest:

1. **[Download the app (no terminal)](https://github.com/Gabriel-Dalton/autohours/releases).** Open `autohours-windows.exe`, or unzip `autohours-macos.zip` and move the app to Applications. The window guides you through ActivityWatch, projects and your billing agreement. Python is included. Keep the app in its final location before enabling nightly runs.
2. **One line in a terminal.** Use the command below for your system. Already installed? Run `autohours gui` for the window or `autohours setup` for text questions. Running `autohours` without arguments also opens the window.
3. **Ask Claude Code or Codex.** Say "Help me set up autohours" and point it at [the setup skill](skills/autohours-setup/SKILL.md). Enter your key yourself in the app or hidden local prompt, never in chat.

The downloads are unsigned. On Windows, choose **More info > Run anyway**. On macOS, right-click the app and choose **Open**. Download only from this repository's releases.

Windows:

```powershell
irm https://raw.githubusercontent.com/Gabriel-Dalton/autohours/main/install.ps1 | iex
```

macOS and Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/Gabriel-Dalton/autohours/main/install.sh | sh
```

The installer checks Python, installs pipx and autohours, and starts the setup questions. On Windows it can install Python with winget. On macOS/Linux it explains how to install Python if needed. Git is needed to download the package. You can inspect [install.ps1](install.ps1) or [install.sh](install.sh) before running it.

Already installed? Run:

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

## Requirements

- Windows, macOS or Linux. Terminal installs need Python 3.11 or newer. Downloads include Python. Use a browser already on your computer.
- [ActivityWatch](https://activitywatch.net/) running with its window and AFK watchers enabled.
- A Clockify account for Clockify exports, or just a local folder for CSV.

The application uses only Python's standard library, plus the `tzdata` time zone package, which is installed automatically on Windows. pytest is for development only. PyInstaller is only in the optional `build` extra. Wayland desktop restrictions can prevent ActivityWatch from capturing window titles; check its dashboard before setup.

## Desktop app

The app opens as its own window using Edge or Chrome already on Windows. On macOS it uses Chrome, Edge or Brave; on Linux it uses an installed Chromium browser. If an app window is unavailable, it opens in your usual browser. The local address is also printed when a terminal is available. No browser download, npm or build step is needed.

The screens follow your system's light or dark appearance, fit narrow windows and larger text, and support keyboard navigation. Enter activates the main action. Errors appear beside the answer that needs fixing. There are no separate pop-up dialogs or sidebar.

1. **Welcome:** see what autohours does, confirm the detected time zone, or search for a different city.
2. **ActivityWatch:** check that the free recorder is running. When it is stopped, download and open it; the app checks again automatically. Choose a computer only when several are available. Website matching is optional.
3. **Where timesheets go:** choose Clockify or a spreadsheet file that opens in Excel, Numbers or Google Sheets. The suggested file is `Documents/autohours-timesheet.csv`.
4. **Connect Clockify:** open your Clockify settings and paste the API key into the local password field, or use a saved key. It is stored using the same private storage as the text wizard and never returned to the page.
5. **Workspace:** choose your Clockify workspace. A single workspace is selected automatically. Spreadsheet setup skips both Clockify screens.
6. **Projects:** add clients or projects inline, pick a project pill, and tick apps, websites or titles from your last seven days. Search the list and see the percentage assigned. The project menu changes names, descriptions and order. Clockify projects can be selected or created when settings are saved.
7. **Billing:** choose how each client is billed, then optional hourly rates and currency, short breaks, calls, rounding and monthly limits. There is no assumed billing type or rate. Clockify suggests the workspace currency; spreadsheet currency starts empty. Save and continue saves everything automatically.
8. **Check and finish:** see connection checks, compare Clockify rates, and review yesterday (or today when yesterday is empty). Writing a day, updating Clockify rates and enabling morning writes each have a separate inline confirmation. Finish opens Home.

**Home** shows the latest morning run for the settings file in use, including its time and outcome. Changing the date or choosing Yesterday or Today reviews that day automatically. Totals use hours and minutes, with hourly amounts when a rate is set. Unmatched activity has an Assign it shortcut; short pieces show the configured minimum. General calculation details are under How is this worked out? Open full report creates a private HTML file in system temp without window titles. Write this day first checks existing entries and monthly limits, then asks for confirmation. The tiles open Projects and billing, the morning schedule, your settings file, or setup again. Editing projects returns home after saving. Changing the morning switch or its inline time shows the exact schedule and requires confirmation.

The web server binds only to `127.0.0.1` on a random port. Each launch exchanges a one-time bootstrap code for a private token stored in the window session. The code expires after 120 seconds and can only be used once. The token never appears in the launch address or browser arguments. The server uses exact Host and Origin checks, and a policy that blocks external scripts, fonts and connections from the page. All assets ship with the app. Window titles stay on this computer. Keep the local address private. Close app stops the server immediately; closing the browser window stops it after 20 seconds without a heartbeat. The first window has 60 seconds to connect.

Long operations run in request threads while the page shows progress. Writes are serialized and retain the existing protection against concurrent writers. Logs are private files in the user config folder under `logs/YYYY-MM-DD.log`, retained for 30 days. A morning run writes yesterday only; it does not backfill missed days. Review again after a partial failure before retrying.

Activity and review screens show loading text while reading. Connection checks and day reviews can run together. The app caches ActivityWatch discovery for 30 seconds and completed days for up to five minutes within the session. Settings changes clear the cache; today's activity and write checks always fetch fresh data. Older logs without a settings-file identifier are omitted from Home because their source cannot be verified.

## Advanced: edit the config yourself

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

   Use exact Clockify project names in `destination_project`, or omit it when `name` is already correct. The [fully commented example](examples/autohours.example.toml) explains every field.

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

After reviewing a successful manual write, the setup wizard can schedule `autohours sync yesterday --write` daily. It previews the commands and asks for separate approval. It uses absolute paths, the installed Python environment, and your user account. Remove its daily job with `autohours schedule --remove`. See [Windows, macOS and Linux examples](docs/scheduling.md) for manual alternatives. Run only one scheduled instance for each destination.

## Set it up with Claude Code or Codex

For Claude Code, copy `skills/autohours-setup/` from this repository into `~/.claude/skills/`. On Windows this is inside your user folder. Then ask: "Use autohours-setup to help me turn my ActivityWatch activity into timesheets."

Codex and other agents can use [AGENTS.md](AGENTS.md). Prefer `autohours setup` in your own terminal. Agents can walk through the same questions and edit the config on your behalf; you should never have to write a regex. If you want help choosing rules, let them inspect a few days of unmatched activity locally and show a preview. Review before approving the first `--write`. The [setup skill](skills/autohours-setup/SKILL.md) walks through this process without assuming you are a programmer.

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

## Building desktop downloads

Install `.[dev,build]` from a copy of the source in your system temp folder so package metadata stays outside the checkout. PyInstaller is a build tool, never a runtime dependency. Build on the target OS. Set `PYTHONDONTWRITEBYTECODE=1` and `PYINSTALLER_CONFIG_DIR` to a system temp directory, then run:

```sh
python -B -m pytest -p no:cacheprovider
python -B -m PyInstaller --clean --noconfirm --workpath /absolute/temp/autohours-work --distpath /absolute/temp/autohours-dist packaging/autohours.spec
```

Replace the example temp paths with paths for your system. The [spec](packaging/autohours.spec) uses a windowed one-file executable on Windows and an app bundle on macOS, following [PyInstaller's spec format](https://pyinstaller.org/en/stable/spec-files.html). Optional icon placeholders are `packaging/autohours.ico` and `packaging/autohours.icns`; the default icon is used until these files are supplied.

Pushing a `v*` tag runs tests and builds both downloads. The workflow attaches them to a **draft** GitHub Release for a human to check and publish. It does not sign or notarize downloads. Before publishing, test first launch, scaling at 125% and 150%, keyboard navigation, and a scheduled run on both systems. Moving an app after scheduling requires removing and recreating its nightly job.
