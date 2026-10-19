# Changelog

## Unreleased

- Line up the Add button and the Yesterday and Today buttons with the fields beside them, and the "per hour in" label with the rate fields, at every window size.
- Keep each screen's heading aligned with the step bar and at the same height from step to step, so the page no longer jumps while Clockify connects.
- Show the Clockify rate check in plain English, hide Update Clockify when nothing would change, and list only the confirmed results afterwards.
- Keep the write confirmation short, with the full technical preview behind "Show the full preview".
- Plainer connection messages: "Open ActivityWatch and try again", "Check your internet connection" for Clockify, and a revoked Clockify key now says to create a new key and run setup again.
- Align the time zone Change link with its text on small screens.
- Clear the "Open ActivityWatch" error as soon as ActivityWatch is detected.
- Show the Workspace step only when you have more than one Clockify workspace, so the step count no longer changes after connecting.
- When ActivityWatch has more than one computer, ask you to choose one instead of saying ActivityWatch is not open.
- Ask before discarding project changes when you go back from editing projects on Home.
- Explain on the billing screen that rounding never runs into the next entry.
- Make the screen after Close app say the app closed as asked, instead of describing a lost connection.
- Add a Known limitations section to the README.
- Show one line per project in the Clockify rate check.
- Treat the mouse back button and Alt+Left as the on-screen Back, instead of leaving the page and closing the app.
- Say when the spreadsheet is open in another program such as Excel, instead of a general error.
- Refuse an existing file with other columns as the spreadsheet at setup, instead of failing at the first write.
- Add `autohours --version`.
- Refreshing the window returns to the same screen, keeping unsaved billing answers, instead of starting setup again.
- Offer up to 500 apps, windows and websites from the last week on the projects screen, instead of only the 20 biggest, so smaller clients can be found and searched.
- "Assign it" opens the projects screen showing only activity no client covers yet, with a switch to show everything.
- Restyle the full report to match the app, in plain language, with a legend of only the colours used and tables that fit a phone.
- Say when website matching is on but the ActivityWatch browser extension has sent nothing, instead of pointing at app recording.
- Rewrite "How is this worked out?" in plain language.
- Show the morning schedule as a plain sentence with the time in your clock format, with the exact command behind "Show the full preview".

## 1.0.2

The 1.0.1 downloads were never published, so 1.0.2 includes everything since 1.0.0.

- Explain in the README why autohours works without AI: your screen history, which can include secrets, never leaves your computer.
- Add the walkthrough video to the README.
- Show the written time in hours and minutes after writing a day, matching the rest of the app.
- When a day is already fully written, say so instead of offering to write 0 entries.
- Show a clear message, with the settings file location, when the app cannot open because the settings file has a problem. Before, the downloaded app closed without saying anything.
- Spreadsheets open accented and non-Latin names correctly in Excel, and names that start with `=`, `+`, `-` or `@` stay as text instead of turning into formulas.
- Keep the selected project tab visible on narrow windows, and shorten very long project names in the tabs.
- Clear an old date error once a valid day loads, and call the daily run "Last morning run" to match the Every morning setting.

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
