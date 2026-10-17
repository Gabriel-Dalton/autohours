# Working on autohours

Keep the project small, cross-platform and standard-library-only at runtime. Python 3.11 is the minimum. Use synthetic fixtures and offline HTTP stubs. Never call real destinations to test, and never commit local activity, keys, personal config or exported timesheets.

## Development

```sh
python -m pip install -e ".[dev]"
python -B -m pytest -p no:cacheprovider
```

Keep `src/autohours/starter.toml` and `examples/autohours.example.toml` identical. Follow the existing source and destination protocols; do not add speculative integrations or runtime dependencies. Validate any new config fields, preserve dry-run behavior, and test overlap handling and privacy boundaries. Docs use plain English and no em or en dashes.

## Helping someone set up timesheets

Use the conversational workflow in [the setup skill](skills/autohours-setup/SKILL.md). Check ActivityWatch is running and recording both windows and AFK time. Ask for timezone, destination and project intent. Preserve their config; `init` refuses to overwrite it.

Explain that unmatched output contains local private titles before inspecting several days with `autohours unmatched DATE`. Propose project rules from actual activity and ask about ambiguous work. Do not upload raw activity or paste it into shared artifacts. Use a user's own summary if they prefer. Put specific rules first; any matching regex wins for the first project. Confirm descriptions and billable status.

For Clockify, have the user set `CLOCKIFY_API_KEY` from Profile settings without revealing it in chat. Never put the key in TOML, scripts or the repository. Use CSV while destination decisions are pending.

When adding a project, ask about its agreement one question at a time: billing type, rate and currency, counted breaks, calls when away, rounding, then monthly cap. Never assume a rate or currency. Write the confirmed agreement under that project, using `[policy]` only for defaults the user wants shared. Billing type controls billable status; `none` is non-billable. For Clockify, run `autohours rates` and show the differences. Only run `rates --apply` after the user confirms the exact project, billable flag, rate and currency. Check readback for mismatches.

Translate "breaks under five minutes count" into `count_breaks_up_to_minutes = 5`, explaining that the limit includes exactly five minutes. Translate "that gap from 2 to 2:30 was a call for Acme, accept it" into `autohours accept DATE 14:00 14:30 --project Acme` after resolving the date and project. Accepted notes stay local. Do not infer other missing work.

Write settings, run `doctor`, test representative titles with `rules test`, then show `review` before any `sync --write`. Run `sync` without `--write` to check destination overlaps and caps. Explain that merging only groups entries: excluded gaps are not billed. Explain duration rounding, short blocks, unmatched time, accepted time and existing-entry skips. Monthly local review can differ from sync, which reserves logged destination time. Only run `--write` after the user approves the dates and destination. Do not delete manual entries. Review again after partial failures, and avoid concurrent writers.

HTML reviews omit titles unless `--titles` is explicit. Keep reviews, accepted files and scheduler logs private and outside source control. Do not create test caches, scratch folders, build or dist output inside the repository; use the system temp directory and disable bytecode and pytest caches during checks.

Scheduling requires approval to automate future writes. Use absolute paths and private environment settings from [scheduling](docs/scheduling.md). Daily yesterday runs do not backfill all missed days. Keep scheduler logs private because previews can include titles.
