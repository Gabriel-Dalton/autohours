# Changelog

## 0.4.0

- Polish the desktop with light and dark palettes, readable fonts, a sidebar stepper, cards, clear focus states and clock icons.
- Add detected time zones, searchable project activity, coverage progress, agreement cards and review summary totals.
- Add home action tiles and installed schedule times, and let Enter continue from the time zone picker.
- Add a Tk desktop wizard and home screen for reviewing days, editing projects and managing nightly runs.
- Share setup, credential verification, activity choices, rule building, saving and review logic with the text wizard.
- Keep slow desktop operations in background threads and require separate approval for external writes.
- Open the window with no arguments, while preserving CLI commands and explicit dry runs.
- Schedule pip and packaged installations using the correct executable and keep private dated logs for 30 days.
- Add an optional build extra, Windows and macOS packaging, and a tag-triggered draft release workflow.
- Put app downloads, terminal installation and agent-assisted setup first in the README.

## 0.3.0

- Add one-line Windows, macOS and Linux installers that start interactive setup.
- Set up CSV or Clockify through numbered questions, with back, quit and add-project flows.
- Build escaped project rules from seven days of local activity and confirm project agreements.
- Verify and save Clockify keys outside TOML, using a Windows user variable or a private credentials file.
- Preview daily scheduling, require approval, and add `schedule --remove` for undo.
- Prevent concurrent writers using the same config.
- Display rates as money per hour and report unchanged settings as in sync.
- Show local review times under date headings, preserving offsets during repeated daylight saving hours.
- Put no-code setup first in the README and update the agent setup workflow.

## 0.2.0

- Validate ActivityWatch time against project agreements and shared policy defaults.
- Fix merged entries billing excluded away gaps; compress billed duration and preserve real spans in review.
- Count agreed short breaks and calls while away, with per-entry nearest or upward rounding.
- Enforce monthly caps against logged destination time and report held-back minutes.
- Add private accepted-time add, list and remove commands, preserving overlap protection.
- Add terminal and self-contained HTML reviews with evidence timelines and hourly totals.
- Compare and explicitly apply Clockify project billable settings and rates, with currency checks and readback.
- Keep runtime dependencies empty; install timezone data separately when required by the OS.

## 0.1.0

- Read local ActivityWatch window, AFK and optional web events.
- Review ordered project matches, unmatched time and daily blocks.
- Export approved blocks to Clockify or CSV, skipping existing overlaps.
- Include setup assistance, scheduling examples and offline tests.
