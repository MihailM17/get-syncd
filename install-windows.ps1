# Get Syncd — Windows installer (PowerShell, run as normal user)
# Requires: Python 3.10+ and git on PATH (winget install Python.Python.3.12 Git.Git)
$ErrorActionPreference = "Stop"
Write-Host "=== Get Syncd — Windows installer ==="

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-Host "Python not found. Install it first:"
  Write-Host "  winget install Python.Python.3.12 Git.Git"
  exit 1
}
Write-Host ("Python found: " + (python --version))

Write-Host "Creating virtual environment..."
python -m venv .venv
& .\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -e .
Write-Host ""
Write-Host "Done! Test it:"
Write-Host "  get-syncd --help"
Write-Host "  pytest -q"
Write-Host ""
Write-Host "Projects live in ~\GetSyncd — same folder layout as macOS/Linux."
Write-Host "In DaVinci Resolve, enable Preferences -> System -> General -> External scripting."
