# StegoLab one-time setup (Windows PowerShell).
#   powershell -ExecutionPolicy Bypass -File setup.ps1          # auto-detects an NVIDIA GPU
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -Cpu     # force CPU-only PyTorch
param([switch]$Cpu)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

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

Step "Creating Python virtual environment (backend/.venv)"
Set-Location "$root\backend"
if (-not (Test-Path .venv)) { & $pyExe @pyArgs -m venv .venv }
$venvPy = "$root\backend\.venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip --quiet

$gpu = (-not $Cpu) -and (Get-Command nvidia-smi -ErrorAction SilentlyContinue)
$index = if ($gpu) { 'https://download.pytorch.org/whl/cu128' } else { 'https://download.pytorch.org/whl/cpu' }
Step "Installing PyTorch ($(if ($gpu) {'CUDA 12.8'} else {'CPU'}))"
& $venvPy -m pip install torch torchvision --index-url $index --quiet
Step "Installing backend dependencies"
& $venvPy -m pip install -r requirements-dev.txt --quiet

Step "Generating backend/.env with random secrets (kept if it already exists)"
& $venvPy "$root\scripts\init_env.py"

Step "Creating the database, admin account, model registry and research results"
& $venvPy -m alembic upgrade head
& $venvPy -m app.cli bootstrap-admin
& $venvPy -m app.cli sync-models
& $venvPy -m app.cli import-experiments

Step "Installing frontend dependencies"
Set-Location "$root\frontend"
npm install --no-fund --no-audit

Set-Location $root
Write-Host "`nSetup complete." -ForegroundColor Green
Write-Host "Start the app with:  powershell -ExecutionPolicy Bypass -File start.ps1"
Write-Host "Admin login: BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD in backend\.env"
