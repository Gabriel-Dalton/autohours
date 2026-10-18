# autohours

[![Tests](https://github.com/Gabriel-Dalton/autohours/actions/workflows/ci.yml/badge.svg)](https://github.com/Gabriel-Dalton/autohours/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)

**Your timesheet, filled in from what you actually worked on.**

autohours reads the activity that [ActivityWatch](https://activitywatch.net/) records on your computer, sorts it into your clients and projects, leaves out the time you were away, and writes the result to Clockify or a spreadsheet. It bills the way you agreed with each client: hourly or flat, with or without short breaks, rounded how you like, up to a monthly limit. You see every entry before anything is written.

![The autohours review screen showing a day of timesheet entries for two clients, with totals for time, entries and amount](docs/images/review.png)

## Get started

You need [ActivityWatch](https://activitywatch.net/downloads/) installed and running. It is free and keeps everything on your computer. Then pick one:

### 1. Download the app (easiest)

Get it from the [latest release](https://github.com/Gabriel-Dalton/autohours/releases/latest):

- **Windows:** download `autohours-windows.exe` and open it.
- **Mac:** download `autohours-macos-apple-silicon.zip` (M1 or newer) or `autohours-macos-intel.zip` (older Intel Macs), unzip it and move **autohours** to Applications. Not sure which? Apple menu > **About This Mac** shows "Chip: Apple" or "Processor: Intel".

Nothing else to install. The window walks you through everything.

The downloads are not signed yet, so your computer asks whether you trust them the first time:

- **Windows:** choose **More info**, then **Run anyway**.
- **Mac:** right-click the app and choose **Open**. If macOS still refuses, open **System Settings > Privacy & Security** and choose **Open Anyway**.

Only download autohours from this repository.

### 2. Install with one line

Paste this into a terminal. It installs what it needs and opens the app.

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/Gabriel-Dalton/autohours/main/install.ps1 | iex
```

Mac and Linux:

```sh
curl -fsSL https://raw.githubusercontent.com/Gabriel-Dalton/autohours/main/install.sh | sh
```

You can read [install.ps1](install.ps1) or [install.sh](install.sh) first. Afterwards, run `autohours` to open the app, or `autohours setup` to answer questions in the terminal instead.

### 3. Ask Claude Code or Codex

Say "Help me set up autohours" and point it at [the setup skill](skills/autohours-setup/SKILL.md). Type your Clockify key into the app or the hidden prompt yourself, never into the chat.

## How setup works

| Pick what you work on | Tell it how you bill |
| --- | --- |
| ![Projects screen: two clients as tabs and last week's apps and window titles with hours, some assigned to each client](docs/images/projects.png) | ![Billing screen: hourly billing selected with a rate of 120 USD and short breaks counted up to 10 minutes](docs/images/billing.png) |

| Welcome | Dark mode |
| --- | --- |
| ![Welcome screen listing what autohours does, with the detected time zone](docs/images/welcome.png) | ![ActivityWatch screen in dark mode confirming ActivityWatch is running](docs/images/activitywatch-dark.png) |

1. **Check ActivityWatch** is running. The app helps you download it if not.
2. **Choose where timesheets go:** Clockify, or a spreadsheet file that opens in Excel, Numbers or Google Sheets.
3. **Add your clients** and tick the apps, websites and windows from last week that belong to each one. There are no rules to write.
4. **Say how you bill each client:** hourly or flat, rate and currency, whether short breaks and calls count, rounding, and any monthly limit.
5. **Check a day** and write it when it looks right. You can turn on a morning run that writes yesterday automatically.

After setup, the home screen shows any day's hours and what you would bill, and lets you assign anything it could not match. Screenshots use made-up demo data.

## Your privacy

- **Window titles and website addresses never leave your computer.** Only the project, your own description, the times and whether it is billable go to Clockify or the spreadsheet.
- There is no account, no tracking and no cloud service. autohours only talks to ActivityWatch on your computer and, if you choose it, Clockify.
- Your Clockify key is kept in your own user settings, never in a project file.
- Nothing is written until you confirm it, and existing entries are never overwritten or deleted.

The activity list in the app shows your private window titles, so check screenshots before you share them. See the [privacy details](docs/how-it-works.md#privacy-details).

## Questions

**Does it cost anything?** No. autohours is free and open source. ActivityWatch is free, and Clockify's free plan is enough.

**What if my laptop was asleep or I stepped away?** That time is not counted, unless your agreement says short breaks or calls count.

**What about work I did away from the computer?** Add it with `autohours accept` or straight in Clockify. autohours never writes over existing entries.

**Can I undo a write?** Delete or edit the entries in Clockify or your spreadsheet. autohours never deletes anything.

**My day looks empty.** Check that ActivityWatch's dashboard shows activity for that day, then use **Assign it** on the home screen to match anything left over.

**Does it guess with AI?** No. It only uses the apps and windows you picked for each client. Nothing is sent to an AI service.

**Can I use the command line or edit the settings file?** Yes. See the [command line guide](docs/command-line.md).

## Learn more

- [The desktop app](docs/desktop-app.md): each screen, and how the local window is secured
- [Command line and settings file](docs/command-line.md)
- [How matching and billing work](docs/how-it-works.md)
- [Scheduling nightly runs](docs/scheduling.md)
- [Clockify details](docs/clockify.md)
- [Contributing and building the downloads](CONTRIBUTING.md)
- [Reporting a security problem](SECURITY.md)
- [Changelog](CHANGELOG.md)

## Credits

The app's design follows the IBM Carbon Design System. Bundled IBM Plex Sans fonts are under the [SIL Open Font License](src/autohours/web/fonts/OFL.txt) and Carbon icons under the [Apache License 2.0](src/autohours/web/icons-LICENSE.txt). autohours is released under the [MIT License](LICENSE).
