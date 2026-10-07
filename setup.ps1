# StegoLab one-time setup (Windows PowerShell).
#   powershell -ExecutionPolicy Bypass -File setup.ps1          # auto-detects an NVIDIA GPU
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -Cpu     # force CPU-only PyTorch
param([switch]$Cpu)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
# Run a native command and stop the setup if it fails (PowerShell 5.1 does not do this by itself).
function Invoke-Checked {
    $exe = $args[0]
    $rest = @($args | Select-Object -Skip 1)
    & $exe @rest
    if ($LASTEXITCODE -ne 0) { throw "Command failed (exit $LASTEXITCODE): $exe $($rest -join ' ')" }
}

# --- Python -------------------------------------------------------------------
$pyExe = $null
$pyArgs = @()
foreach ($candidate in 'py -3.12', 'py -3.11', 'python3.12', 'python') {
    $parts = $candidate -split ' '
    $exe = $parts[0]
    $extra = @($parts | Select-Object -Skip 1)
    if (Get-Command $exe -ErrorAction SilentlyContinue) {
        $version = & $exe @extra -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($version -and [version]$version -ge [version]'3.11') { $pyExe = $exe; $pyArgs = $extra; break }
    }
}
if (-not $pyExe) { throw 'Python 3.11+ is required (3.12 recommended): https://www.python.org/downloads/' }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw 'Node.js 20+ is required: https://nodejs.org/' }
if ($root.Length -gt 80) {
    Write-Warning "The project path is long ($($root.Length) chars). PyTorch has deeply nested files; if pip fails with a"
    Write-Warning "'path too long' error, clone to a short path such as C:\Stenography or enable Windows long paths."
}

Step "Creating Python virtual environment (backend/.venv)"
Set-Location "$root\backend"
if (-not (Test-Path .venv)) { Invoke-Checked $pyExe @pyArgs -m venv .venv }
$venvPy = "$root\backend\.venv\Scripts\python.exe"
Invoke-Checked $venvPy -m pip install --upgrade pip --quiet

$gpu = (-not $Cpu) -and (Get-Command nvidia-smi -ErrorAction SilentlyContinue)
$index = if ($gpu) { 'https://download.pytorch.org/whl/cu128' } else { 'https://download.pytorch.org/whl/cpu' }
Step "Installing PyTorch ($(if ($gpu) {'CUDA 12.8'} else {'CPU'}))"
Invoke-Checked $venvPy -m pip install torch torchvision --index-url $index --quiet
Step "Installing backend dependencies"
Invoke-Checked $venvPy -m pip install -r requirements-dev.txt --quiet

Step "Generating backend/.env with random secrets (kept if it already exists)"
Invoke-Checked $venvPy "$root\scripts\init_env.py"

Step "Creating the database, admin account, model registry and research results"
Invoke-Checked $venvPy -m alembic upgrade head
Invoke-Checked $venvPy -m app.cli bootstrap-admin
Invoke-Checked $venvPy -m app.cli sync-models
Invoke-Checked $venvPy -m app.cli import-experiments

Step "Installing frontend dependencies"
Set-Location "$root\frontend"
Invoke-Checked npm install --no-fund --no-audit

Set-Location $root
Write-Host "`nSetup complete." -ForegroundColor Green
Write-Host "Start the app with:  powershell -ExecutionPolicy Bypass -File start.ps1"
Write-Host "Admin login: BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD in backend\.env"
