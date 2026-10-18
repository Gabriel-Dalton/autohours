#!/bin/sh
# Run: curl -fsSL https://raw.githubusercontent.com/Gabriel-Dalton/autohours/main/install.sh | sh
autohours_install() (
    fail() { printf '\n%s\n' "autohours stopped: $1" >&2; exit 1; }
    printf '%s\n' 'Welcome to autohours. Checking for Python 3.11 or newer...'
    if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
        if [ "$(uname -s)" = Darwin ]; then
            fail 'Install Python with brew install python, or from https://www.python.org/downloads/macos/ . Then run this installer again.'
        fi
        fail 'Install Python 3.11 or newer using your distribution package manager (for example python3, python3-pip and python3-venv on Debian/Ubuntu), then run this installer again. See https://www.python.org/downloads/ .'
    fi
    command -v git >/dev/null 2>&1 || fail 'Git is needed to download autohours. Install Git using your system package manager or https://git-scm.com/downloads and try again.'
    printf '%s\n' 'Checking pipx, which keeps autohours separate from other Python programs...'
    if command -v pipx >/dev/null 2>&1; then
        pipx_run() { pipx "$@"; }
    elif python3 -m pipx --version >/dev/null 2>&1; then
        pipx_run() { python3 -m pipx "$@"; }
    else
        printf '%s\n' 'Installing pipx for your user account...'
        if python3 -m pip install --user pipx; then
            pipx_run() { python3 -m pipx "$@"; }
        else
            # Managed system Python may reject pip --user. Do not override that protection.
            printf '%s\n' 'Your system manages Python packages. Installing pipx in its own private environment instead...'
            autohours_pipx="${XDG_DATA_HOME:-$HOME/.local/share}/autohours-installer/pipx"
            python3 -m venv "$autohours_pipx" || fail 'Could not create a Python environment. Install your distribution python3-venv and pipx packages, then try again.'
            "$autohours_pipx/bin/python" -m pip install pipx || fail 'Could not install pipx. Check your connection and try again.'
            pipx_run() { "$autohours_pipx/bin/python" -m pipx "$@"; }
        fi
    fi
    pipx_run ensurepath || fail 'Could not add pipx programs to your PATH. Check the message above and try again.'
    printf '%s\n' 'Installing autohours...'
    pipx_run install git+https://github.com/Gabriel-Dalton/autohours --python "$(command -v python3)" --force || fail 'Installation failed. Check your connection and the messages above, then try again.'
    autohours_bin=$(pipx_run environment --value PIPX_BIN_DIR) || fail 'Could not find the pipx programs folder.'
    [ -x "$autohours_bin/autohours" ] || fail 'autohours was not found after installation. Check the pipx messages above.'
    if [ "$(uname -s)" = Darwin ] || [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
        printf '%s\n' 'Installation complete. Opening the autohours window, which walks you through setup.'
        printf '%s\n' 'Prefer questions in this terminal? Close the window and run: autohours setup'
        "$autohours_bin/autohours" </dev/null || fail 'The window needs attention. Run autohours setup for terminal questions.'
    else
        printf '%s\n' 'Installation complete. No desktop found, so starting the question-by-question setup...'
        # curl | sh owns stdin. Read questions and hidden input from the terminal instead.
        "$autohours_bin/autohours" setup </dev/tty || fail 'Setup needs attention. Run autohours setup in an interactive terminal to continue.'
    fi
)
autohours_install
