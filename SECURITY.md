# Security

autohours handles a Clockify API key and runs a small web server on your own computer for the desktop window, so security reports matter.

## Reporting a problem

Please do not open a public issue for a security problem. Report it privately through [GitHub's private vulnerability reporting](https://github.com/Gabriel-Dalton/autohours/security/advisories/new) for this repository.

Include what you found, how to reproduce it, and which version and operating system you used. Never include a real API key, window titles or other private activity; use made-up examples. You should get a reply within a week. Fixes are released as soon as they are ready, and you are credited unless you prefer not to be.

## Supported versions

Only the latest release receives security fixes.

## How autohours protects you

- The desktop window talks to a server bound only to `127.0.0.1` on a random port. Each launch uses a one-time code that expires after 120 seconds and is exchanged for a private session token. The token never appears in the launch address, process arguments or logs.
- Every request checks the exact Host and Origin, and the page runs under a strict content security policy with no external scripts, fonts or connections.
- The Clockify key is stored in your Windows user environment, or in a private credentials file with permissions 600 on macOS and Linux. It is never written to the settings file, sent to the page or logged.
- Window titles and URLs never go to Clockify or the spreadsheet. autohours sends no telemetry.
- Downloads are built by GitHub Actions from tagged source and attached to a draft release that a person checks before publishing. They are not code signed yet.

More detail is in [the desktop app guide](docs/desktop-app.md) and [privacy details](docs/how-it-works.md#privacy-details).
