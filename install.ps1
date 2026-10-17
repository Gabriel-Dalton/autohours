# Run in PowerShell: irm https://raw.githubusercontent.com/Gabriel-Dalton/autohours/main/install.ps1 | iex
& {
    $ErrorActionPreference = 'Stop'
    function Refresh-AutohoursPath {
        $env:PATH = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
            [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + $env:PATH
    }
    function Find-AutohoursPython {
        foreach ($candidate in @(@('py', '-3'), @('py', '-3.12'), @('python'), @('python3'))) {
            if (Get-Command $candidate[0] -ErrorAction SilentlyContinue) {
                $program = $candidate[0]
                $arguments = @($candidate | Select-Object -Skip 1)
                try {
                    $pythonPath = & $program @arguments -c 'import sys; print(sys.executable) if sys.version_info >= (3, 11) else sys.exit(1)' 2>$null
                } catch { continue }
                if ($LASTEXITCODE -eq 0 -and $pythonPath) { return $pythonPath.Trim() }
            }
        }
        $installed = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
        if (Test-Path -LiteralPath $installed) { return $installed }
        return $null
    }
    try {
        Write-Host 'Welcome to autohours. Checking for Python 3.11 or newer...'
        $autohoursPython = Find-AutohoursPython
        if (-not $autohoursPython) {
            if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
                throw 'Install Python 3.11 or newer from https://www.python.org/downloads/windows/ and run this installer again.'
            }
            Write-Host 'Python is missing or too old. Installing Python 3.12 with winget now.'
            winget install -e --id Python.Python.3.12
            if ($LASTEXITCODE -ne 0) { throw 'Python installation did not finish. Install it from https://www.python.org/downloads/windows/ and try again.' }
            Refresh-AutohoursPath
            $autohoursPython = Find-AutohoursPython
            if (-not $autohoursPython) { throw 'Python was installed, but is not available yet. Open a new PowerShell window and run this installer again.' }
        }
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
            if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
                throw 'Git is needed to download autohours. Install it from https://git-scm.com/downloads/win and run this installer again.'
            }
            Write-Host 'Installing Git with winget so pipx can download autohours.'
            winget install -e --id Git.Git
            if ($LASTEXITCODE -ne 0) { throw 'Git installation did not finish. Please install Git and try again.' }
            Refresh-AutohoursPath
            if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Open a new PowerShell window and run this installer again so Git is available.' }
        }
        Write-Host 'Checking pipx, which keeps autohours separate from other Python programs...'
        & $autohoursPython -c "import importlib.util,sys; sys.exit(importlib.util.find_spec('pipx') is None)"
        if ($LASTEXITCODE -ne 0) {
            Write-Host 'Installing pipx for your user account.'
            & $autohoursPython -m pip install --user pipx
            if ($LASTEXITCODE -ne 0) { throw 'Could not install pipx. Check your internet connection and Python installation, then try again.' }
        }
        & $autohoursPython -m pipx ensurepath
        if ($LASTEXITCODE -ne 0) { throw 'Could not add pipx programs to your PATH. Check your user environment settings and try again.' }
        Write-Host 'Installing autohours...'
        & $autohoursPython -m pipx install git+https://github.com/Gabriel-Dalton/autohours --python $autohoursPython --force
        if ($LASTEXITCODE -ne 0) { throw 'autohours installation failed. Check your connection and the messages above, then try again.' }
        $autohoursBin = & $autohoursPython -m pipx environment --value PIPX_BIN_DIR
        if ($LASTEXITCODE -ne 0 -or -not $autohoursBin) { throw 'Could not find the pipx programs folder. Open a new terminal and run autohours setup.' }
        $autohoursCommand = Join-Path $autohoursBin.Trim() 'autohours.exe'
        if (-not (Test-Path -LiteralPath $autohoursCommand)) { throw 'autohours was not found after installation. Check the pipx messages above.' }
        Write-Host 'Installation complete. Starting the question-by-question setup...'
        & $autohoursCommand setup
        if ($LASTEXITCODE -ne 0) { throw 'Setup needs attention. Follow the message above, then run autohours setup again.' }
    } catch {
        Write-Host ('autohours stopped: ' + $_.Exception.Message)
    }
}
