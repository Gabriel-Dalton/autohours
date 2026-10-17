---
name: autohours-setup
description: Help a user configure autohours from their local ActivityWatch activity, review project rules and previews, and export approved timesheets to Clockify or CSV.
---

# Set up autohours conversationally

Install this skill by copying this entire `autohours-setup` folder into `~/.claude/skills/`. On Windows, use the `.claude/skills` folder inside the user's home directory. Codex and other agents can follow the repository's AGENTS.md instead.

Ask for their timezone, destination and intended projects in plain English. Preserve existing settings. Do not treat setup as permission to write timesheets or enable a schedule.

1. Check Python 3.11+ and install this repository with `python -m pip install .` or `pipx install .`. On Windows, if `zoneinfo` has no IANA data, install `tzdata` into the same environment, or use `pipx inject autohours tzdata`.
2. Check ActivityWatch is running locally at `http://localhost:5600` and that window and AFK watchers are recording. If several hosts are present, ask which computer to use. Do not combine hosts. URL matching requires the browser extension, host metadata and a foreground title match; offer it only when useful.
3. Run `autohours init` if no config exists. Edit the timezone before interpreting dates. Start with CSV while credentials or project decisions are pending. For Clockify, have the user set `CLOCKIFY_API_KEY` themselves from Profile settings. Never ask them to paste the key into chat and never store it in TOML, scripts or source control.
4. Explain that unmatched output contains private local window titles. With their agreement to inspect this data, run `autohours unmatched yesterday` and the same command for two or three relevant explicit dates. Do not upload raw output or copy it into shared docs. If they prefer not to expose titles to an agent, have them summarize the projects themselves.
5. Propose projects and regexes based on their observed work, rather than generic guesses. Ask about ambiguous titles. Explain that any title, app or URL rule can match, and the first matching project wins. Put specific projects above general ones. Use single-quoted TOML regex strings. Keep descriptions fixed and safe for the destination. Confirm billable status rather than assuming it.
6. Write the config. Explain merge gaps can add elapsed time; recommend zero if the user wants strict active-time accounting. Run `autohours rules test` on representative titles and `autohours doctor`. Fix missing watchers, wrong project names and environment problems using its messages.
7. Run `autohours preview` over the selected days, then `autohours sync` for the same dates without `--write`. Show totals, unmatched time, discarded short blocks and existing-entry skips. Adjust rules with the user until the proposed entries are useful.
8. Only run `autohours sync ... --write` after the user explicitly approves the dates and destination. Existing entries win on overlap; never delete or modify manual entries to force a sync. After a partial failure, preview again before retrying. Do not run concurrent writers.
9. Offer scheduling only after a successful manual run and separate approval to automate writes. Follow `docs/scheduling.md`, using absolute paths and a private environment for the key. Explain that daily `yesterday` runs do not backfill several missed days.

Stop for missing user choices that affect billing or external writes. Routine read-only checks and reversible config edits can proceed within the user's setup request. Never invent activity when the laptop slept, the phone was used, or AFK coverage is missing.
