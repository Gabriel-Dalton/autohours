# Changelog

## 1.0.1

- Explain in the README why autohours works without AI: your screen history, which can include secrets, never leaves your computer.
- Add the walkthrough video to the README.
- Show the written time in hours and minutes after writing a day, matching the rest of the app.
- When a day is already fully written, say so instead of offering to write 0 entries.

## 1.0.0

First public release, with downloadable Windows and macOS apps.

- Restyle the desktop app on the IBM Carbon design system with bundled IBM Plex Sans and Carbon icons, a centred layout that grows with the window, selectable tiles and subtle motion.
- Exchange a one-time launch code for the session token so the token never appears in process arguments, and ignore disconnects when the window closes.
- Give the app window a sharp icon and its own taskbar icon on Windows, smooth the packaged app icons, and size the window to the screen.
- Restyle notifications without coloured side stripes, keep icons visible after the app closes, use specific error messages, and show a clear screen when the app has closed.
- Make the one-line installers open the desktop app, falling back to terminal questions on Linux without a desktop.
- Shorten the README for first-time users and move technical detail into `docs/` and `CONTRIBUTING.md`. Add `SECURITY.md`.
- Replace the Tk window with a modern local web app using bundled HTML, CSS and vanilla JavaScript, with no new runtime dependency or build step.
- Open an app window in an installed browser, with a regular browser fallback and a printed local address.
- Protect the loopback server with per-launch tokens, exact Host and Origin checks, security headers, an allowlisted static route table and heartbeat shutdown.
- Add light and dark themes, responsive cards, keyboard navigation, visible focus, reduced motion, inline validation and confirmations.
- Add automatic ActivityWatch checks, conditional download links, detected time zones, inline projects, searchable activity and coverage.
- Require a billing choice, keep rates optional, suggest the verified workspace currency and save automatically before Check and finish.
- Clean app name suffixes such as .Root and .exe without changing activity matching.
- Add a home dashboard with day reviews, private HTML reports, project editing and separately approved morning schedules.
- Keep setup, credentials, billing and config logic shared with the text wizard. Serialize writes and require fresh previews for rate changes, day writes and schedules.
- Record written hours after overlap checks and show a concise recent-run summary.
- Open the app with no arguments while preserving CLI commands and explicit dry runs.
- Ship web assets in wheels and packaged apps, retain the icon generator, and keep unsigned downloads on draft releases for human review.
- Test API security, setup parity, credential privacy, validation, confirmations, browser discovery and server lifetime with synthetic offline services.

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
