# Working on autohours

Keep the project small, cross-platform and standard-library-only at runtime, plus Windows-only tzdata. The local web app uses only bundled HTML, CSS and JavaScript. PyInstaller belongs only in the optional build extra. Python 3.11 is the minimum. Use synthetic fixtures and offline HTTP stubs. Never call real destinations to test, and never commit local activity, keys, personal config or exported timesheets.

## Development

```sh
python -m pip install -e ".[dev]"
python -B -m pytest -p no:cacheprovider
```

Keep `src/autohours/starter.toml` and `examples/autohours.example.toml` identical. Follow the existing source and destination protocols; do not add speculative integrations or runtime dependencies. Validate any new config fields, preserve dry-run behavior, and test overlap handling and privacy boundaries. Docs use plain English and no em or en dashes.

## Helping someone set up timesheets

Prefer the desktop app or `autohours gui` for people who have never used a terminal. Otherwise use `autohours setup` in the user's own interactive terminal, or `autohours setup --add-project` for an existing config. Agents may follow its steps and edit the config on the user's behalf. Never make a non-technical user edit a file or write a regex. Keys must be entered by the user at the hidden local prompt, never through chat or an agent transcript.

Use the conversational workflow in [the setup skill](skills/autohours-setup/SKILL.md). Check ActivityWatch is running and recording both windows and AFK time. Ask for timezone, destination and project intent. Preserve their config; `init` refuses to overwrite it.

Explain that unmatched output contains local private titles before inspecting several days with `autohours unmatched DATE`. Propose project rules from actual activity and ask about ambiguous work. Do not upload raw activity or paste it into shared artifacts. Use a user's own summary if they prefer. Put specific rules first; any matching regex wins for the first project. Confirm descriptions and billable status.

For Clockify, prefer the wizard's hidden key prompt (Profile settings, API, Generate) without revealing it in chat. Setup saves a Windows user environment variable, or a mode-600 credentials file in the user config folder on macOS/Linux. `CLOCKIFY_API_KEY` overrides the file. Never put the key in TOML, scripts or the repository. Use CSV while destination decisions are pending.

When adding a project, ask about its agreement one question at a time: billing type, rate and currency, counted breaks, calls when away, rounding, then monthly cap. Never assume a rate or currency. Write the confirmed agreement under that project, using `[policy]` only for defaults the user wants shared. Billing type controls billable status; `none` is non-billable. For Clockify, run `autohours rates` and show the differences. Only run `rates --apply` after the user confirms the exact project, billable flag, rate and currency. Check readback for mismatches.

Translate "breaks under five minutes count" into `count_breaks_up_to_minutes = 5`, explaining that the limit includes exactly five minutes. Translate "that gap from 2 to 2:30 was a call for Acme, accept it" into `autohours accept DATE 14:00 14:30 --project Acme` after resolving the date and project. Accepted notes stay local. Do not infer other missing work.

Write settings, run `doctor`, test representative titles with `rules test`, then show `review` before any `sync --write`. Run `sync` without `--write` to check destination overlaps and caps. Explain that merging only groups entries: excluded gaps are not billed. Explain duration rounding, short blocks, unmatched time, accepted time and existing-entry skips. Monthly local review can differ from sync, which reserves logged destination time. Only run `--write` after the user approves the dates and destination. Do not delete manual entries. Review again after partial failures, and avoid concurrent writers.

HTML reviews omit titles unless `--titles` is explicit. Keep reviews, accepted files and scheduler logs private and outside source control. Do not create test caches, scratch folders, build or dist output inside the repository; use the system temp directory and disable bytecode and pytest caches during checks.

Setup previews the exact schedule and requires separate approval to automate future writes. `autohours schedule --remove` undoes the generated daily job. Use absolute paths and private environment settings from [scheduling](docs/scheduling.md). Daily yesterday runs do not backfill all missed days. Keep scheduler logs private because previews can include titles.

## Desktop and release work

Share setup decisions through plain functions in setup.py and desktop.py; keep the text wizard compatible. webapp.py wraps Session with a loopback-only ThreadingHTTPServer. Serve only the bundled web/index.html, app.css and app.js, with no third-party runtime packages, CDNs, npm or build step. Keep billing and config logic in Python. Run slow operations in request threads and serialize changes and writes with a lock. Exchange a one-time, 120-second bootstrap code at POST /api/session; keep the real token out of launch URLs, process arguments and logs. Require the per-launch token on every other API request, exact Host and Origin checks, CSP, no-store and nosniff headers. Never return a Clockify key or traceback to the page. Stop after 20 seconds without a heartbeat, allow 60 seconds for the first, and support explicit quit.

Follow the Carbon tokens already in app.css. Never add decorative coloured stripes (left or top accent borders) to messages, cards or panels: status colour lives only in the status icon, and messages use a neutral 1px border. Error messages name the problem and the next step, never a generic headline. Use inline validation and confirmation panels, visible labels and focus, keyboard controls, reduced-motion support and light and dark themes. Keep the layout usable from 360px and at Windows scaling of 125% to 150%. Save automatically when continuing from billing. Rates, day writes and future automatic writes still need separate approval of the actual preview. Use synthetic offline services for API and browser checks. Test security, setup parity, confirmation safeguards, heartbeat shutdown and cross-platform browser discovery. Localhost socket tests may skip only when binding is not permitted.

No-argument launch opens the app; arguments retain the CLI. Frozen schedules invoke sys.executable directly. Pip schedules use sys.executable -B -m autohours. Keep logs in the private user config folder, retain 30 days, and show friendly errors without keys or tracebacks. App setup never authorizes rate changes, timesheet writes or nightly writes by itself.

Build only in system temp, including package metadata and PyInstaller caches. A v* tag creates unsigned Windows and macOS downloads on a draft release. A human checks and publishes it. Do not publish or sign automatically.
