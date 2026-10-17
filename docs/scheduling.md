# Run yesterday's sync daily

The easiest route is `autohours setup`. After an approved manual write, it offers a daily run at 06:00 by default. It shows the exact task command, launchd plist, or new user crontab before asking for approval. Times use the computer's clock. One autohours daily schedule is managed per user account; creating another replaces it. Other cron jobs remain intact. Remove the generated job with `autohours schedule --remove`.

The generated schedule uses the absolute path of the Python environment running setup and an absolute config path. Writers using the same config cannot overlap. Different configs that share a destination still need separate coordination. macOS and Linux logs are private files in the user config directory. Windows uses Task Scheduler's task history and result status.

Clockify keys saved by setup are available to future runs: the Windows user environment, or the private `credentials` file in the default user config folder on macOS/Linux. The `CLOCKIFY_API_KEY` environment variable takes priority. No key is put in a task command, plist or crontab. If you use this saved key, the manual environment and wrapper steps below are unnecessary.

## Manual alternatives

First run `doctor`, `preview yesterday` and a manually approved `sync yesterday --write`. Set an absolute config path and executable path. Find the executable with `Get-Command autohours` in PowerShell or `command -v autohours` on macOS/Linux. Replace example paths with your own. These examples run at 18:00, when a laptop is more likely to be awake. The computer must have ActivityWatch running and recording during work.

Each job runs `autohours sync yesterday --write`. The date is evaluated in the config's timezone; the scheduler's clock determines when the job starts. CSV needs no API key. Clockify needs `CLOCKIFY_API_KEY` in the job's environment. Never put a real key in the config, task command, plist or repository. These commands create schedules that write automatically; use them only after approving that behavior.

## Windows Task Scheduler

Set `CLOCKIFY_API_KEY` as a user environment variable using Windows' **Edit environment variables for your account** settings, then sign out and back in so new scheduled tasks inherit it. Run under that same account. Keep **Do not start a new instance** selected under the task's settings.

From Command Prompt, using paths without spaces in this example:

```bat
schtasks /Create /TN AutohoursDaily /SC DAILY /ST 18:00 /TR "C:\Tools\autohours.exe --config C:\Timesheets\autohours.toml sync yesterday --write" /IT
```

For paths containing spaces, use Task Scheduler's **Create Basic Task** wizard. Put the full executable path in **Program/script**, and `--config "C:\My Timesheets\autohours.toml" sync yesterday --write` in **Add arguments**. Select **Run only when user is logged on**. Use **Run** to test and check **Last Run Result**. A value of 0 means success. Enable **Run task as soon as possible after a scheduled start is missed** if useful. This still processes only yesterday, not every missed date.

## macOS launchd

Save this as `~/Library/LaunchAgents/local.autohours.daily.plist`. Replace `/Users/you` and the executable path with your paths. XML paths do not expand `~` or environment variables.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>local.autohours.daily</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/you/.local/bin/autohours</string>
    <string>--config</string><string>/Users/you/Timesheets/autohours.toml</string>
    <string>sync</string><string>yesterday</string><string>--write</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>/Users/you/Timesheets/autohours.log</string>
  <key>StandardErrorPath</key><string>/Users/you/Timesheets/autohours-error.log</string>
</dict>
</plist>
```

Create the log folder first. For Clockify, read the key privately into the launchd environment from a terminal:

```sh
read -r -s CLOCKIFY_API_KEY
export CLOCKIFY_API_KEY
launchctl setenv CLOCKIFY_API_KEY "$CLOCKIFY_API_KEY"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/local.autohours.daily.plist"
```

Type the key after `read`, then press Enter. `launchctl setenv` must be repeated after login. For unattended persistence, use a local wrapper that retrieves the key from your chosen credential manager before executing the same command. Check both logs after testing with `launchctl kickstart "gui/$(id -u)/local.autohours.daily"`. launchd prevents concurrent instances of this job.

## Linux cron

Use `crontab -e`. This assumes `/usr/bin/flock` is available, prevents concurrent cron instances, and runs under your user account:

```cron
0 18 * * * /usr/bin/flock -n /home/you/Timesheets/autohours.lock /home/you/.local/bin/autohours --config /home/you/Timesheets/autohours.toml sync yesterday --write >> /home/you/Timesheets/autohours.log 2>&1
```

Cron does not inherit your interactive shell's API key. For Clockify, use a private wrapper that exports `CLOCKIFY_API_KEY` from a credential manager or protected file, then `exec`s the command above. Keep credentials outside the repository. Use systemd below if you prefer a separate environment file.

## Linux systemd user timer

Create `~/.config/systemd/user/autohours.service`:

```ini
[Unit]
Description=Write yesterday's approved activity rules to timesheets

[Service]
Type=oneshot
EnvironmentFile=-%h/.config/autohours/clockify.env
ExecStart=%h/.local/bin/autohours --config %h/Timesheets/autohours.toml sync yesterday --write
```

For Clockify only, create `~/.config/autohours/clockify.env` containing `CLOCKIFY_API_KEY=YOUR_API_KEY`, replace the placeholder locally, and restrict it with `chmod 600 ~/.config/autohours/clockify.env`. Do not commit this file. Omit it for CSV. A credential manager wrapper avoids keeping the key in a file.

Create `~/.config/systemd/user/autohours.timer`:

```ini
[Unit]
Description=Daily autohours sync

[Timer]
OnCalendar=*-*-* 18:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable and inspect:

```sh
systemctl --user daemon-reload
systemctl --user enable --now autohours.timer
systemctl --user list-timers
journalctl --user -u autohours.service
```

A oneshot service will not overlap itself. Use either cron or systemd, not both. Persistent timers catch a missed trigger, but still process only yesterday. After several days away, review an explicit date range and sync it manually.

## Logs and missed runs

Preview output includes unmatched titles. Restrict access to scheduler logs and delete old logs when no longer needed. Do not publish them in bug reports. A nonzero exit status means an error. Run `doctor` in the same account/environment to diagnose it. Check that the executable still exists after reinstalling or moving Python.
