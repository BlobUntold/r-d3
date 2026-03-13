Param(
    [string]$WinPythonPath = "",
    [string]$VenvPath = "C:\\Users\\u249989\\conway_env",
    [switch]$UseSpec
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

# Determine python executable: prefer explicit WinPythonPath, else look for python in PATH
if ($WinPythonPath -and (Test-Path $WinPythonPath)) {
    $PY = $WinPythonPath
} else {
    try {
        $cmd = Get-Command python -ErrorAction Stop
        $PY = $cmd.Source
    } catch {
        Write-Host "No Python executable found. Please download WinPython (slim/whl) and pass its python.exe via -WinPythonPath, or add python to PATH." -ForegroundColor Yellow
        exit 1
    }
}

Write-Host "Using Python: $PY"

# Create venv if it doesn't exist
if (-not (Test-Path $VenvPath)) {
    & $PY -m venv $VenvPath
}

# Activate venv for the current script
. "$VenvPath\Scripts\Activate.ps1"

# Upgrade pip and build tools
python -m pip install --upgrade pip setuptools wheel

# Install requirements preferring binary wheels
python -m pip install --prefer-binary -r "$scriptDir\requirements.txt"

# Build with PyInstaller (adjust add-data entries if your assets folder differs)
Push-Location $scriptDir
if ($UseSpec) {
    if (Test-Path "$scriptDir\ConwayWar.spec") {
        pyinstaller ConwayWar.spec
    } else {
        Write-Host "ConwayWar.spec not found in $scriptDir" -ForegroundColor Yellow
        pyinstaller --onedir --windowed --name "ConwayWar" --add-data "assets;assets" ..\conways_game.py
    }
} else {
    pyinstaller --onedir --windowed --name "ConwayWar" --add-data "assets;assets" ..\conways_game.py
}
Pop-Location

Write-Host "Build finished. See ..\dist\ConwayWar"
