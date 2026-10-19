# Changelog

## Unreleased

### Fixed

- Renaming or removing a client after adding time away for it stopped every review, write and morning run with "Invalid accepted time". Time away now follows a renamed client, and time away for a removed client is ignored.
- A quick second click while an earlier action was still finishing could show "Another check or save is still running". The app now waits a moment and retries.
- The website and README said every day is reviewed before it is written; they now say Every morning writes on its own once you turn it on.

## 1.0.4

Log the work that happens away from your desk, set up several clients faster, and meet autohours' new website.

### Highlights

- **Time away from the computer.** Add a call, meeting or site visit for a client on Home. It counts as work, and your private note never reaches the timesheet.
- **A shorter billing screen.** Each client folds into one line that sums up how you bill them, so you can check every client at a glance.
- **A website.** [autohours.vercel.app](https://autohours.vercel.app) shows what autohours does in a few seconds, with a step-by-step walkthrough, the video and the right download for your computer.

### New

- **Time away from the computer** on Home: pick the client, the from and to times and an optional note. Overlapping or impossible times get a clear message, and removing one leaves anything already written in your timesheet.
- **[autohours.vercel.app](https://autohours.vercel.app):** an animated example of activity becoming a timesheet, a scroll-through of the three setup steps, a video player that falls back to an Unmute button when a browser blocks sound, and a download button that picks Windows or Mac. Phones and tablets are told to download on a computer.

### Improved

- With several clients, the billing screen folds each one into a summary line, such as "By the hour, 120 CAD, breaks up to 10 min". The first client still to answer opens, a client with a missing answer opens to show it, and "Same as" keeps the client you copied into open.

### Docs

- Release notes now open with a summary and highlights, followed by New, Improved, Fixed and Docs, and the contributor guide explains the format.
- The README and desktop app guide cover time away from the computer and link to the website.
- The website is private by design: no analytics or cookies, strict security headers and a `security.txt`.

## 1.0.3

A big polish release from a full test of the app, including a run against a real Clockify workspace. Setup is harder to get stuck in, messages say what to do next, and finding and assigning your activity is much easier.

### Highlights

- **Find every client's work.** The client screen now lists up to 500 apps, windows and websites from your last week instead of only the 20 biggest, and "Assign it" shows only the activity no client covers yet.
- **No more dead ends.** Refreshing the window keeps your place, the mouse back button no longer closes the app, and you can switch between a spreadsheet and Clockify without starting over.
- **Clearer everywhere.** Error messages name the problem and the next step, and the full report has been redesigned to match the app.

### New

- "Same as" on the billing screen copies the previous client's answers.
- "Only show activity with no client" switch on the client screen.
- Switch an existing setup between a spreadsheet and Clockify, keeping your clients, activity and billing.
- `autohours --version`.

### Improved

- Up to 500 apps, windows and websites to choose from, so smaller clients can be found and searched.
- "Assign it" opens the client screen showing only activity no client covers yet.
- The full report matches the app, uses plain language, lists only the colours used and fits a phone.
- Clockify rate checks read in plain English, show one line per client, and hide Update Clockify when nothing would change.
- The write confirmation is one sentence, with the technical detail behind "Show the full preview".
- The morning schedule is described in a sentence, in your clock format, with the exact command behind "Show the full preview".
- "How is this worked out?" is rewritten in plain language, and an empty day says why it is empty.
- The app says "client" throughout, and "monthly limit" consistently.
- Headings line up with the step bar and stay put from step to step.
- The terminal setup asks for a rate only for hourly clients, like the app, and lists activity in hours and minutes.

### Fixed

- Refreshing the window sent you back to Welcome. It now returns to the same screen and keeps unsaved billing answers.
- The mouse back button or Alt+Left left the page and closed the app. It now acts like the on-screen Back.
- Switching from a spreadsheet to Clockify asked you to remove every client first, on a screen you could not reach.
- A spreadsheet open in Excel showed a general error. It now says to close it there.
- An unrelated file was accepted as the spreadsheet and failed at the first write. Setup now refuses it.
- A deleted or renamed Clockify project showed project IDs. It now names the client and how to fix it.
- Connection messages pointed at the wrong fix, and a revoked Clockify key mentioned a developer setting.
- Website matching without the browser extension blamed app recording.
- With two computers in ActivityWatch, continuing without choosing one said ActivityWatch was not open.
- Edits to clients from Home were lost without warning when going back. The app now asks first.
- The Workspace step appeared and disappeared during setup.
- The "Open ActivityWatch" error stayed on screen after ActivityWatch started.
- The screen after Close app described a lost connection.
- The Add button, the Yesterday and Today buttons, the "per hour in" label and the time zone Change link were out of line at some window sizes.

### Docs

- Known limitations in the README: Mac is experimental, Linux is not supported.
- The desktop app guide describes all of the above.

## 1.0.2

Safer spreadsheets and clearer messages, found in the first full test of the app. The 1.0.1 downloads were never published, so 1.0.2 includes everything since 1.0.0.

### Highlights

- **Spreadsheets that open cleanly in Excel,** including accented and non-English client names.
- **A clear message when the app cannot open,** instead of closing without a word.

### Improved

- After writing a day, the time written is shown in hours and minutes.
- A day that is already written says so, instead of offering to write 0 entries.
- The selected client tab stays visible on narrow windows, and very long names are shortened.
- The daily run is called "Last morning run" to match the Every morning setting.

### Fixed

- The downloaded app closed silently when the settings file had a problem. It now shows a message with the file's location.
- Accented and non-Latin names were garbled in Excel.
- Client names starting with `=`, `+`, `-` or `@` turned into spreadsheet formulas.
- An old date error stayed on screen after a valid day loaded.

### Docs

- The README explains why autohours works without AI: your screen history, which can include secrets, never leaves your computer.
- The walkthrough video is in the README.

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
