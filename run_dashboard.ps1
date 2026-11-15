# Start the dashboard, but only if the environment is installed and every
# serving file exists. Extra arguments are passed on to `streamlit run`.
Set-Location $PSScriptRoot

$VenvDir = ".venv"
$AppPath = "src/app/main.py"
$ServingFiles = @("players", "valuations", "records", "transfers", "clubs_and_competitions", "predictions")

function Fail($Message) {
    Write-Host "Error: $Message" -ForegroundColor Red
    exit 1
}

$Python = Join-Path $VenvDir "Scripts/python.exe"
if (-not (Test-Path $Python)) {
    Fail "No environment found at $VenvDir. Run 'uv sync' first."
}

& $Python -c "import streamlit" 2>$null
if ($LASTEXITCODE -ne 0) {
    Fail "Streamlit is not installed in $VenvDir. Run 'uv sync' first."
}

$ServingDir = & $Python -c "from transferformance.configs import DIR_SRC_APP_SERVING; print(DIR_SRC_APP_SERVING)" 2>$null | Select-Object -Last 1
if ($LASTEXITCODE -ne 0 -or -not $ServingDir) {
    Fail "The transferformance package is not installed in $VenvDir. Run 'uv sync' first."
}

$Missing = $ServingFiles | Where-Object { -not (Test-Path (Join-Path $ServingDir "$_.parquet")) } | ForEach-Object { "$_.parquet" }
if ($Missing) {
    Fail "Missing serving files in ${ServingDir}: $($Missing -join ', '). Run the pipeline first (.\run_pipeline.ps1)."
}

if (-not (Test-Path $AppPath)) {
    Fail "App file not found at $AppPath."
}

& $Python -m streamlit run $AppPath @args
exit $LASTEXITCODE