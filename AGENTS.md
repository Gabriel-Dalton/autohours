# Working on autohours

Keep the project small, cross-platform and standard-library-only at runtime. Python 3.11 is the minimum. Use synthetic fixtures and offline HTTP stubs. Never call real destinations to test, and never commit local activity, keys, personal config or exported timesheets.

## Development

```sh
python -m pip install -e ".[dev]"
python -m pytest
```

If the OS lacks IANA timezone data, install `tzdata` in the environment. Keep `src/autohours/starter.toml` and `examples/autohours.example.toml` identical. Follow the existing source and destination protocols; do not add speculative integrations or runtime dependencies. Validate any new config fields, preserve dry-run behavior, and test overlap handling and privacy boundaries. Docs use plain English and no em or en dashes.

## Helping someone set up timesheets

Use the conversational workflow in [the setup skill](skills/autohours-setup/SKILL.md). Check ActivityWatch is running and recording both windows and AFK time. Ask for timezone, destination and project intent. Preserve their config; `init` refuses to overwrite it.

Explain that unmatched output contains local private titles before inspecting several days with `autohours unmatched DATE`. Propose project rules from actual activity and ask about ambiguous work. Do not upload raw activity or paste it into shared artifacts. Use a user's own summary if they prefer. Put specific rules first; any matching regex wins for the first project. Confirm descriptions and billable status.

For Clockify, have the user set `CLOCKIFY_API_KEY` from Profile settings without revealing it in chat. Never put the key in TOML, scripts or the repository. Use CSV while destination decisions are pending. Windows may need timezone data via `pip install tzdata` or `pipx inject autohours tzdata`.

Write settings, run `doctor`, test representative titles with `rules test`, then run `preview` and `sync` without `--write`. Explain merge gaps, rounding, short blocks, unmatched time and existing-entry skips. Only run `--write` after the user approves the dates and destination. Do not delete manual entries or infer missing activity. Preview again after partial failures, and avoid concurrent writers.

Scheduling requires approval to automate future writes. Use absolute paths and private environment settings from [scheduling](docs/scheduling.md). Daily yesterday runs do not backfill all missed days. Keep scheduler logs private because previews can include titles.
