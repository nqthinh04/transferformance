# Exit immediately if any command fails
$ErrorActionPreference = "Stop"

Write-Host "==> 1. Installing uv..." -ForegroundColor Cyan
# Install uv via PowerShell official installer
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Refresh environment PATH so 'uv' is accessible in the current session
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")

Write-Host "==> 2. Cloning repository..." -ForegroundColor Cyan
git clone https://github.com/nqthinh04/transferformance.git
Set-Location transferformance

Write-Host "==> 3. Syncing project dependencies with uv..." -ForegroundColor Cyan
uv sync

Write-Host "==> 4. Running pipeline: Raw download..." -ForegroundColor Cyan
uv run python -m transferformance.raw.download

Write-Host "==> 5. Running pipeline: Interim build..." -ForegroundColor Cyan
uv run python -m transferformance.interim.build

Write-Host "==> 6. Running pipeline: Processed build..." -ForegroundColor Cyan
uv run python -m transferformance.processed.build --hist

Write-Host "==> 7. Running pipeline: Serving database build..." -ForegroundColor Cyan
uv run python -m transferformance.serving.build_from_database

Write-Host "==> 8. Running pipeline: Serving model build..." -ForegroundColor Cyan
uv run python -m transferformance.serving.build_from_model

Write-Host "==> 9. Launching Streamlit app..." -ForegroundColor Cyan
uv run streamlit run ./src/app/main.py